import csv
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.inputs import Revision
from app.modules.release import service
from app.modules.release.reader import SCHEDULED, UNDER_REVIEW
from app.modules.release.roster import OLD_VERSION, NEW_VERSION

EFFECTIVE = '2026-01-01'


def revision_csv(rows):
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['档案件', '状态', '保管政策'])
    writer.writerows(rows)
    return stream.getvalue().encode()


def payload(client, rows, effective=EFFECTIVE):
    return client.post('/api/release/roster',
                       json={'revision': revision_csv(rows).decode(), 'effective_date': effective})


def test_each_entry_carries_policy_version(client, source):
    rows = [
        ['00101', SCHEDULED, '2024-01-01/2025-01-01/1'],
        ['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1'],
    ]
    body = payload(client, rows).json()['roster']
    versions = {entry['key']: entry['policy_version'] for entry in body['releasable'] + body['retained']}
    assert versions['00101'] == OLD_VERSION
    assert versions['00104'] == NEW_VERSION


def test_scheduled_kept_under_old_terms_even_if_new_releases(client):
    # 00104 旧年限 2 年仍须保管；若按新 1 年限则可放行。已排期必须冻结旧年限。
    rows = [['00104', SCHEDULED, '2020-01-01/2030-01-01/1']]
    body = payload(client, rows).json()['roster']
    entry, = body['retained']
    assert entry['key'] == '00104' and entry['policy_version'] == OLD_VERSION
    assert entry['verdict'] == '继续保管' and body['releasable'] == []


def test_under_review_recomputed_with_new_terms(client):
    rows = [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]
    body = payload(client, rows).json()['roster']
    entry, = body['releasable']
    assert entry['key'] == '00104' and entry['policy_version'] == NEW_VERSION
    assert entry['earliest_disposal'] == '2026-01-01'


def test_two_versions_never_release_same_case(client):
    # 同一案件在两份名单里：一份已排期（旧，须保管），一份复核中（新，可放行），互斥集合不相交
    scheduled = payload(client, [['00104', SCHEDULED, '2020-01-01/2030-01-01/1']]).json()['roster']
    reviewed = payload(client, [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]).json()['roster']
    old_keys = {e['key'] for e in scheduled['releasable']}
    new_keys = {e['key'] for e in reviewed['releasable']}
    assert old_keys.isdisjoint(new_keys)
    assert scheduled['exclusive'] and reviewed['exclusive']


def test_idempotent_same_revision_no_duplicate(client):
    rows = [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]
    first = payload(client, rows).json()
    second = payload(client, rows).json()
    assert first['roster']['roster_id'] == second['roster']['roster_id']
    assert first['created'] is True and second['created'] is False
    assert len(client.get('/api/release/roster').json()['rosters']) == 1


def test_concurrent_preparation_one_roster(client, source):
    rows = revision_csv([['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']])
    revision = Revision(revision=rows.decode(), effective_date=EFFECTIVE)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: service.prepare(revision), range(4)))
    assert len({roster['roster_id'] for roster, _ in outcomes}) == 1
    assert len(client.get('/api/release/roster').json()['rosters']) == 1


def test_switch_is_atomic_and_rollback_restores_old(client):
    first = payload(client, [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]).json()['roster']
    second = payload(client, [['00101', SCHEDULED, '2024-01-01/2025-01-01/1']]).json()['roster']
    client.post(f"/api/release/roster/{first['roster_id']}/switch")
    assert client.get('/api/release/active').json()['roster']['roster_id'] == first['roster_id']
    switched = client.post(f"/api/release/roster/{second['roster_id']}/switch").json()
    assert switched['previous'] == first['roster_id']
    assert client.get('/api/release/active').json()['roster']['roster_id'] == second['roster_id']
    restored = client.post('/api/release/rollback').json()
    assert restored['active'] == first['roster_id']
    assert client.get('/api/release/active').json()['roster']['roster_id'] == first['roster_id']


def test_failed_switch_keeps_old_roster(client, monkeypatch):
    old = payload(client, [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]).json()['roster']
    client.post(f"/api/release/roster/{old['roster_id']}/switch")
    missing = client.post('/api/release/roster/not-exist/switch')
    assert missing.status_code == 404 and missing.json()['code'] == 'ROSTER_UNKNOWN'
    assert client.get('/api/release/active').json()['roster']['roster_id'] == old['roster_id']


def test_switch_failure_mid_transaction_rolls_back(client, monkeypatch):
    # 在备份已写、替换未提交时制造故障，验证事务整体回滚：旧名单仍有效且无脏备份
    from app.modules.release import repository
    first = payload(client, [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]).json()['roster']
    second = payload(client, [['00103', UNDER_REVIEW, '2020-01-01/2026-01-01/1']]).json()['roster']
    client.post(f"/api/release/roster/{first['roster_id']}/switch")

    real_connection = repository.connection

    class Poisoned:
        def __init__(self, db):
            self.db = db
            self.real_execute = db.execute

        def __getattr__(self, name):
            return getattr(self.db, name)

        def execute(self, sql, params=()):
            if sql.strip().startswith('INSERT OR REPLACE INTO active_roster'):
                raise RuntimeError('模拟切换写入故障')
            return self.real_execute(sql, params)

    def poisoned_connection():
        cm = real_connection()
        db = cm.__enter__()

        class Wrapped:
            def __enter__(self_inner):
                return Poisoned(db)

            def __exit__(self_inner, *exc):
                return cm.__exit__(*exc)
        return Wrapped()

    monkeypatch.setattr(repository, 'connection', poisoned_connection)
    with pytest.raises(RuntimeError):
        repository.switch(second['roster_id'])

    assert client.get('/api/release/active').json()['roster']['roster_id'] == first['roster_id']
    assert client.get('/api/release/history').json()['backups'] == []


def test_rollback_without_backup_is_refused(client):
    response = client.post('/api/release/rollback')
    assert response.status_code == 409 and response.json()['code'] == 'ROSTER_NO_BACKUP'


def test_restored_backup_is_consumed_not_reused(client):
    first = payload(client, [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]).json()['roster']
    second = payload(client, [['00103', UNDER_REVIEW, '2020-01-01/2026-01-01/1']]).json()['roster']
    client.post(f"/api/release/roster/{first['roster_id']}/switch")
    client.post(f"/api/release/roster/{second['roster_id']}/switch")
    # 回滚到 first：该备份被消费，历史清空，当前名单不回灌，避免无限来回
    restored = client.post('/api/release/rollback')
    assert restored.status_code == 200 and restored.json()['active'] == first['roster_id']
    assert client.get('/api/release/active').json()['roster']['roster_id'] == first['roster_id']
    assert client.get('/api/release/history').json()['backups'] == []
    exhausted = client.post('/api/release/rollback')
    assert exhausted.status_code == 409 and exhausted.json()['code'] == 'ROSTER_NO_BACKUP'


def test_multiple_switches_keep_each_backup_and_restore_latest(client):
    rosters = [
        payload(client, [['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1']]).json()['roster'],
        payload(client, [['00103', UNDER_REVIEW, '2020-01-01/2026-01-01/1']]).json()['roster'],
        payload(client, [['00101', SCHEDULED, '2024-01-01/2025-01-01/1']]).json()['roster'],
    ]
    for roster in rosters:
        client.post(f"/api/release/roster/{roster['roster_id']}/switch")
    # 每次切换都备份前一份，历史里保留前两份（首份切换前无有效名单，无备份）
    backups = [item['roster_id'] for item in client.get('/api/release/history').json()['backups']]
    assert backups == [rosters[1]['roster_id'], rosters[0]['roster_id']]
    # 回滚最近一次 -> 恢复第二份
    got = client.post('/api/release/rollback').json()
    assert got['active'] == rosters[1]['roster_id']


def test_release_sets_are_disjoint_across_versions(client):
    # 业务不变量：任何生成的名单内，旧版放行集合与新版放行集合互不相交，且带互斥标记
    rows = [
        ['00101', SCHEDULED, '2024-01-01/2025-01-01/1'],
        ['00103', UNDER_REVIEW, '2020-01-01/2026-01-01/1'],
        ['00104', UNDER_REVIEW, '2020-01-01/2030-01-01/1'],
        ['00106', UNDER_REVIEW, '2010-01-01/2025-01-01/3'],
    ]
    roster = payload(client, rows).json()['roster']
    old = {e['key'] for e in roster['releasable'] if e['policy_version'] == OLD_VERSION}
    new = {e['key'] for e in roster['releasable'] if e['policy_version'] == NEW_VERSION}
    assert old.isdisjoint(new) and roster['exclusive'] is True
    assert roster['counts']['old_version_release'] == len(old)
    assert roster['counts']['new_version_release'] == len(new)
    # 每个可放行件都带明确的年限版本
    assert all(e['policy_version'] in (OLD_VERSION, NEW_VERSION) for e in roster['releasable'])


def test_revision_key_must_be_accepted(client):
    response = payload(client, [['99999', UNDER_REVIEW, '2020-01-01/2030-01-01/1']])
    assert response.status_code == 422 and response.json()['code'] == 'REVISION_KEY'


def test_invalid_status_rejected(client):
    response = payload(client, [['00104', '冻结', '2020-01-01/2030-01-01/1']])
    assert response.status_code == 422 and response.json()['code'] == 'REVISION_STATUS'


def test_new_policy_that_fails_isolation_blocks_roster(client):
    # 两条政策同时命中结案日 -> ARCHIVE_POLICY，整份名单不出
    response = payload(client, [['00104', UNDER_REVIEW,
                                 '2020-01-01/2026-01-01/1;2023-01-01/2030-01-01/3']])
    assert response.status_code == 422 and response.json()['code'] == 'REVISION_UNRESOLVED'


def test_sample_revision_runs(client):
    response = client.post('/api/release/roster',
                           json={'effective_date': EFFECTIVE})
    assert response.status_code == 200
    roster = response.json()['roster']
    assert roster['counts']['revised'] == 4 and roster['exclusive'] is True
    keys = {entry['key']: entry['policy_version'] for entry in roster['releasable']}
    assert keys.get('00104') == NEW_VERSION and keys.get('00101') == OLD_VERSION

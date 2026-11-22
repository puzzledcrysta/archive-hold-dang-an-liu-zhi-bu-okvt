from hashlib import sha256
from app.errors import DataError
from app.settings import RULE_VERSION
from app.evidence import finding
from app.pipeline import stages
from app.modules.domain.rule import evaluate
from .reader import parse_revision, SCHEDULED

OLD_VERSION = '旧年限（原清单）'
NEW_VERSION = '新年限（修订生效）'
RELEASE = '可处置'


def _proof_date(proof, label):
    for metric, value, _ in proof:
        if metric == label:
            return str(value)
    return None


def build_roster(source, revision, effective):
    """按修订状态分流，生成一次切换后的可放行名单。

    已排期案件冻结旧年限；复核中案件按修订后新年限重算。
    两版放行集合互不相交，互斥失败直接拒绝整份名单。
    """
    report = stages(source)
    revision_report = parse_revision(revision)
    directives = revision_report['directives']
    ready = {record['key']: record for record in report['quality']['ready']}
    missing = sorted(key for key in directives if key not in ready)
    if missing:
        raise DataError('REVISION_KEY', f'修订档案件在有效来源中缺失或未采信: {", ".join(missing)}')

    entries, old_release, new_release, blocked = [], set(), set(), []
    for key in sorted(directives):
        directive = directives[key]
        record = ready[key]
        fields = record['fields']
        if directive['status'] == SCHEDULED:
            policy_version, override = OLD_VERSION, None
        else:
            policy_version, override = NEW_VERSION, directive['policy']
        try:
            amount, proof = evaluate(fields, policy_override=override,
                                     policy_version=policy_version, effective=effective)
        except DataError as error:
            blocked.append(finding(record, error.code, f'{key} 按{policy_version}重算失败: {error}'))
            continue
        verdict = next(value for metric, value, _ in proof if metric == '查询判定')
        entry = {
            'key': key, 'line': record['line'], 'revision': record['revision'],
            'schedule_status': directive['status'], 'policy_version': policy_version,
            'verdict': verdict, 'amount': format(amount, 'f'),
            'earliest_disposal': _proof_date(proof, '最早处置日'),
            'original_disposal': _proof_date(proof, '原最早处置日'),
            'policy_applied': override or fields['保管政策'],
            'proof': [{'metric': label, 'value': str(value), 'unit': unit} for label, value, unit in proof],
        }
        entries.append(entry)
        if verdict == RELEASE:
            (old_release if policy_version == OLD_VERSION else new_release).add(key)

    if blocked:
        raise DataError('REVISION_UNRESOLVED', '存在无法按修订重算的档案件，名单未生成', 422)
    overlap = sorted(old_release & new_release)
    if overlap:
        raise DataError('ROSTER_CONFLICT', f'同一档案件被两版同时列为可处置: {", ".join(overlap)}')

    releasable = [entry for entry in entries if entry['verdict'] == RELEASE]
    retained = [entry for entry in entries if entry['verdict'] != RELEASE]
    digest = sha256(revision).hexdigest()
    roster_id = sha256(f'{RULE_VERSION}:{digest}:{effective}'.encode()).hexdigest()
    return {
        'roster_id': roster_id,
        'revision_sha256': digest,
        'effective_date': effective,
        'rule_version': RULE_VERSION,
        'counts': {
            'revised': len(entries), 'scheduled': sum(1 for e in entries if e['schedule_status'] == SCHEDULED),
            'under_review': sum(1 for e in entries if e['schedule_status'] != SCHEDULED),
            'releasable': len(releasable), 'retained': len(retained),
            'old_version_release': len(old_release), 'new_version_release': len(new_release),
        },
        'exclusive': not overlap,
        'releasable': releasable,
        'retained': retained,
        'quarantine': report['rejected'],
    }

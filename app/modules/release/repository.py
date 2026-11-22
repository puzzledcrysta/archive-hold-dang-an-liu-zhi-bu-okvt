import json
from datetime import datetime, timezone
from app.errors import DataError
from app.store import connection

ACTIVE_ID = 'active'


def save_roster(roster_id, source, revision, payload):
    """幂等写入同一份修订生成的名单；重复重跑返回既有有效名单，不另建。"""
    created = datetime.now(timezone.utc).isoformat()
    record = {**payload, 'stored_at': created}
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT result FROM rosters WHERE id=?', (roster_id,)).fetchone()
        if existing is not None:
            return json.loads(existing['result']), False
        db.execute('INSERT INTO rosters(id, source, revision, result, created) VALUES (?,?,?,?,?)',
                   (roster_id, source, revision, json.dumps(record, ensure_ascii=False), created))
        return record, True


def get_roster(roster_id):
    with connection() as db:
        row = db.execute('SELECT result FROM rosters WHERE id=?', (roster_id,)).fetchone()
        if row is None:
            raise DataError('ROSTER_UNKNOWN', '没有此名单', 404)
        return json.loads(row['result'])


def list_rosters():
    with connection() as db:
        rows = db.execute('SELECT id, created FROM rosters ORDER BY created DESC, id DESC LIMIT 50').fetchall()
        return [dict(row) for row in rows]


def active_roster():
    with connection() as db:
        row = db.execute('''SELECT r.result FROM active_roster a
                            JOIN rosters r ON r.id = a.roster_id WHERE a.slot=?''',
                         (ACTIVE_ID,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0])


def switch(roster_id):
    """原子切换有效名单。先备份当前名单，任一步失败整体回滚，旧名单不被覆盖。"""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        target = db.execute('SELECT 1 FROM rosters WHERE id=?', (roster_id,)).fetchone()
        if target is None:
            raise DataError('ROSTER_UNKNOWN', '没有此名单', 404)
        previous = db.execute('SELECT roster_id FROM active_roster WHERE slot=?', (ACTIVE_ID,)).fetchone()
        previous_id = previous['roster_id'] if previous else None
        switched = datetime.now(timezone.utc).isoformat()
        if previous_id is not None:
            db.execute('INSERT OR REPLACE INTO roster_history(roster_id, archived_at, note) VALUES (?,?,?)',
                       (previous_id, switched, '切换前备份的有效名单'))
        db.execute('INSERT OR REPLACE INTO active_roster(slot, roster_id, switched_at) VALUES (?,?,?)',
                   (ACTIVE_ID, roster_id, switched))
        return {'active': roster_id, 'previous': previous_id, 'switched_at': switched}


def rollback():
    """恢复最近一次被替换的旧版名单；无备份时明确拒绝，绝不清空有效名单。"""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT roster_id FROM active_roster WHERE slot=?', (ACTIVE_ID,)).fetchone()
        backup = db.execute('''SELECT roster_id, archived_at FROM roster_history
                               ORDER BY archived_at DESC, rowid DESC LIMIT 1''').fetchone()
        if backup is None:
            raise DataError('ROSTER_NO_BACKUP', '没有可恢复的旧版名单', 409)
        backup_id, backup_at = backup[0], backup[1]
        target = db.execute('SELECT 1 FROM rosters WHERE id=?', (backup_id,)).fetchone()
        if target is None:
            raise DataError('ROSTER_UNKNOWN', '备份名单原件已缺失，无法恢复', 410)
        restored = datetime.now(timezone.utc).isoformat()
        db.execute('INSERT OR REPLACE INTO active_roster(slot, roster_id, switched_at) VALUES (?,?,?)',
                   (ACTIVE_ID, backup_id, restored))
        # 恢复即消费该备份：撤销一次切换后，当前名单不再回灌历史，避免无限来回回滚
        db.execute('DELETE FROM roster_history WHERE roster_id=? AND archived_at=?',
                   (backup_id, backup_at))
        return {'active': backup_id, 'previous': current['roster_id'] if current else None,
                'restored_at': restored}


def history():
    with connection() as db:
        rows = db.execute('''SELECT h.roster_id, h.archived_at, h.note FROM roster_history h
                             ORDER BY h.archived_at DESC, h.rowid DESC''').fetchall()
        return [dict(row) for row in rows]

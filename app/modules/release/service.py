from .reader import parse_revision
from .repository import save_roster, get_roster, list_rosters, active_roster, switch, rollback, history
from .roster import build_roster


def prepare(payload):
    """计算并幂等保存切换名单。同一份修订重跑不重复生成有效名单。"""
    source, revision, effective = payload.raw(), payload.revision_bytes(), payload.effective_date
    roster = build_roster(source, revision, effective)
    stored, created = save_roster(roster['roster_id'], source, revision, roster)
    return stored, created


def activate(roster_id):
    return switch(roster_id)


def restore():
    return rollback()


def current():
    return active_roster()


def detail(roster_id):
    return get_roster(roster_id)


def listing():
    return list_rosters()


def backups():
    return history()


__all__ = ['prepare', 'activate', 'restore', 'current', 'detail', 'listing', 'backups',
           'parse_revision', 'build_roster']

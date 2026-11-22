from app.errors import DataError
from app.settings import KEY
from app.modules.intake.reader import decode, records

REVISION_FIELDS = (KEY, '状态', '保管政策')
SCHEDULED = '已排期'
UNDER_REVIEW = '复核中'
STATUS = (SCHEDULED, UNDER_REVIEW)


def parse_revision(payload):
    """解析年限修订文件：档案件,状态,保管政策。返回按档案件去重后的修订指令。"""
    text, encoding = decode(payload)
    rows = iter(records(text))
    _, header = next(rows, (0, []))
    if header != list(REVISION_FIELDS):
        raise DataError('HEADER', f'修订表表头须为 {",".join(REVISION_FIELDS)}')
    directives, seen = {}, set()
    for line, row in rows:
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != 3:
            raise DataError('WIDTH', f'修订表第 {line} 行列数须为 3')
        key, status, policy = (value.strip() for value in row)
        if not key:
            raise DataError('REQUIRED', f'修订表第 {line} 行缺少档案件')
        if key in seen:
            raise DataError('REVISION_DUP', f'档案件 {key} 在修订表中重复出现')
        seen.add(key)
        if status not in STATUS:
            raise DataError('REVISION_STATUS', f'档案件 {key} 的状态须为 {SCHEDULED} 或 {UNDER_REVIEW}')
        if not policy:
            raise DataError('REQUIRED', f'档案件 {key} 缺少修订后保管政策')
        directives[key] = {'key': key, 'line': line, 'status': status, 'policy': policy}
    if not directives:
        raise DataError('HEADER_ONLY', '修订表没有可执行的修订行')
    return {'directives': directives, 'encoding': encoding}

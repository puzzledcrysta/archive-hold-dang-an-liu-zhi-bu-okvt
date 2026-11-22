from datetime import date
from decimal import Decimal as D
from app.errors import DataError
from .values import calendar, whole, parts


def intervals(text, code, valued=False):
    resolved = []
    for item in parts(text):
        values = item.split('/')
        if len(values) != (3 if valued else 2):
            raise DataError(code, '区段须有开始和结束日期')
        start, end = calendar(values[0]), calendar(values[1])
        if start >= end:
            raise DataError(code, '区段结束日期须晚于开始')
        resolved.append((start,end,whole(values[2],1,100) if valued else None))
    return sorted(resolved)


def evaluate(row):
    closed, as_of = calendar(row['结案日']),calendar(row['查询日'])
    if as_of < closed or closed.year > 9800:
        raise DataError('ARCHIVE_DATES', '查询日须不早于结案，结案年份至多 9800')
    policies = intervals(row['保管政策'],'ARCHIVE_POLICY',True)
    applicable = [(a,b,years) for a,b,years in policies if a <= closed < b]
    if len(applicable) != 1:
        raise DataError('ARCHIVE_POLICY', '结案日须恰好命中一条保管政策')
    policy_start, _, years = applicable[0]
    try:
        expiry = closed.replace(year=closed.year+years)
    except ValueError:
        expiry = date(closed.year+years,3,1)
    eligible = expiry
    proof = [('保管政策生效',policy_start,''),('原最早处置日',expiry,'')]
    for start,end,_ in intervals(row['留置区段'],'ARCHIVE_HOLD'):
        if start <= eligible < end:
            eligible = end
            proof.append((f'{start} 至 {end} 留置',eligible,''))
    proof.extend([('最早处置日',eligible,''),('查询判定','可处置' if as_of>=eligible else '继续保管','')])
    return D((eligible-closed).days), proof

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ROOT = ROOT / 'sample_data'
DB = Path(os.getenv('WORKBENCH_DB', str(ROOT/'state/ledger.sqlite3')))
TITLE = '档案留置簿'
SLUG = 'archive-hold'
KEY = '档案件'
FIELDS = ('结案日', '查询日', '保管政策', '留置区段')
ROLE = '企业档案室保管员'
UNIT = '天'
RULE_VERSION = 'archive-hold-1.0'
SIGNATURE = '政策与留置'
TABS = {'intake': '移交清单', 'contract': '政策字段', 'quality': '档案异常', 'domain': '处置日期', 'reconcile': '保管台账', 'runs': '留置批次', 'review': '处置复核', 'release': '年限切换'}

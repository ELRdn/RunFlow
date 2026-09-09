from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_local_surface_repair import measurement_record
from runflow.shape_fullbody import write


def test_view_metadata_does_not_promote_incomplete_stage(tmp_path):
    metadata=tmp_path/'verification/chosen/chosen/metrics/views.json'
    metadata.parent.mkdir(parents=True)
    write(metadata,dict(complete=True,views={'front+':{'axis':0}}))
    run=dict(label='chosen-views',command=['worker','--part','views'],complete=False)
    value=measurement_record(tmp_path,'chosen',run)
    assert value['result'] is None
    assert value['diagnostic_partial_result']['complete']
    run['complete']=True
    value=measurement_record(tmp_path,'chosen',run)
    assert value['result']['views']['front+']['axis']==0
    assert value['diagnostic_partial_result'] is None

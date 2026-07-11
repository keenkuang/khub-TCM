SKIN = {'痤疮': '肺经风热', '色斑': '肝郁气滞', '皱纹': '气血两虚', '敏感': '阴虚火旺'}
def diagnose(symptom):
    for k,v in SKIN.items():
        if k in symptom: return {'syndrome': v, 'symptom': k}
    return {'syndrome': '辨证不明', 'symptom': symptom}

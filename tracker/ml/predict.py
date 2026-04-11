import os
import numpy as np
import xgboost as xgb
from django.conf import settings

model = xgb.XGBRegressor()
model.load_model(
    os.path.join(settings.BASE_DIR, "tracker", "ml", "xgboost_cycle_model.json")
)

def predict_cycle(features):
    features = np.array(features).reshape(1, -1)
    return float(model.predict(features)[0])
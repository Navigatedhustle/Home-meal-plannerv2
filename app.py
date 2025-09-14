from __future__ import annotations
import os, random, datetime, io
from dataclasses import dataclass
from typing import Any, Dict, List
from flask import Flask, render_template, request, send_file, make_response
from mealplanner.services.meals_loader import load_meals
from mealplanner.services.planner import (ACTIVITY_FACTORS, grams_from_kcal, compute_tdee, mifflin_st_jeor, 
                                         filter_meals, pick_day_plan, aggregate_grocery)
from mealplanner.services import pdfgen

APP_NAME = "Home Meal Planner"
app = Flask(__name__, template_folder="mealplanner/templates", static_folder="mealplanner/static")
MEALS = load_meals(os.path.join(os.path.dirname(__file__), "mealplanner/data/meals.json"))

@dataclass
class Result:
    token: str
    tdee: int
    target_kcal: int
    days: int
    meals_per_day: int
    p_g: int
    c_g: int
    f_g: int
    plan: List[List[Dict[str,Any]]]
    day_totals: List[int]
    grocery: Dict[str,int]

_RESULTS: Dict[str, Dict[str, Any]] = {}

@app.context_processor
def inject_globals():
    return {"app_name": APP_NAME, "activities": ACTIVITY_FACTORS, "year": datetime.datetime.now().year}

@app.get("/")
def index():
    return render_template("index.html", result=None)

@app.post("/generate")
def generate():
    form = request.form
    tdee_raw = form.get("tdee","").strip()
    activity = form.get("activity","sedentary")
    if tdee_raw:
        try:
            tdee = int(float(tdee_raw))
        except Exception:
            tdee = 0
    else:
        sex = form.get("sex","male")
        age = int(form.get("age","30") or 30)
        try:
            ft = float(form.get("height_ft") or 0)
            inch = float(form.get("height_in") or 0)
            height_cm = (ft*12 + inch) * 2.54
        except Exception:
            height_cm = float(form.get("height_cm") or 175)
        try:
            lb = float(form.get("weight_lb") or 0)
            weight_kg = lb * 0.45359237 if lb else None
        except Exception:
            weight_kg = None
        if weight_kg is None:
            weight_kg = float(form.get("weight_kg") or 80.0)
        bmr = mifflin_st_jeor(sex, age, float(height_cm), float(weight_kg))
        tdee = int(round(compute_tdee(bmr, activity)))
    days = max(1, min(7, int(form.get("days","3"))))
    meals_per_day = max(2, min(5, int(form.get("meals_per_day","3"))))
    prefs = {"vegetarian": bool(form.get("vegetarian")), "vegan": bool(form.get("vegan")), "dairy_free": bool(form.get("dairy_free")), "gluten_free": bool(form.get("gluten_free")), "excludes": form.get("excludes","")}
    target_kcal = int(round(tdee * 0.75))
    p_g, c_g, f_g = grams_from_kcal(target_kcal)
    pool = filter_meals(MEALS, prefs) or MEALS[:]
    plan, totals = [], []
    for _ in range(days):
        picks, total = pick_day_plan(target_kcal, pool, meals_per_day)
        plan.append(picks); totals.append(total)
    grocery = aggregate_grocery(plan)
    token = str(random.randint(10**9, 10**10-1))
    _RESULTS[token] = {"tdee": tdee, "target_kcal": target_kcal, "days": days, "meals_per_day": meals_per_day, "p_g": p_g, "c_g": c_g, "f_g": f_g, "plan": plan, "day_totals": totals, "grocery": grocery}
    result = Result(token, tdee, target_kcal, days, meals_per_day, p_g, c_g, f_g, plan, totals, grocery)
    return render_template("index.html", result=result)

@app.get("/pdf/<token>")
def pdf(token: str):
    data = _RESULTS.get(token)
    if not data:
        return make_response("Session expired. Please regenerate.", 410)
    try:
        blob = pdfgen.build_pdf(data)
    except RuntimeError:
        return make_response("PDF engine not installed. Run: pip install reportlab", 501)
    return send_file(io.BytesIO(blob), as_attachment=True, download_name=f"meal_plan_{token}.pdf", mimetype="application/pdf")

if __name__ == "__main__":
    # Safe single-process dev server; if your host blocks sockets, use: flask --app app offline
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, use_reloader=False, threaded=False)

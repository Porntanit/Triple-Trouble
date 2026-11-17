"""Deterministic adult maintenance estimate; no model-generated calorie prescription."""

import math

ACTIVITY_FACTORS = {
    "Mostly seated": 1.2,
    "Lightly active": 1.375,
    "Moderately active": 1.55,
    "Very active": 1.725,
}
FIELDS = ("age", "height_cm", "weight_kg", "energy_equation")


def validate(data):
    if not any(data.get(key) not in (None, "") for key in FIELDS):
        return dict.fromkeys(FIELDS)
    result = {}
    for field, lower, upper in (("age", 18, 100), ("height_cm", 100, 250), ("weight_kg", 30, 350)):
        value = data.get(field)
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not lower <= value <= upper
        ):
            raise ValueError(f'{field.replace("_", " ")} must be between {lower} and {upper}.')
        if field == "age" and type(value) is not int:
            raise ValueError("Age must be a whole number.")
        result[field] = value
    equation = data.get("energy_equation")
    if equation not in ("female", "male"):
        raise ValueError("Select an equation for the energy estimate.")
    result["energy_equation"] = equation
    return result


def estimate(profile):
    if not all(profile.get(key) is not None for key in FIELDS):
        return None
    offset = -161 if profile["energy_equation"] == "female" else 5
    resting = 10 * profile["weight_kg"] + 6.25 * profile["height_cm"] - 5 * profile["age"] + offset
    if resting <= 0:
        raise ValueError(
            "These measurements do not produce a usable energy estimate. Check your profile."
        )
    factor = ACTIVITY_FACTORS[profile["activity_level"]]
    return {
        "resting_kcal": round(resting),
        "activity_factor": factor,
        "daily_target": round(resting * factor),
        "method": "Mifflin–St Jeor × activity factor",
    }

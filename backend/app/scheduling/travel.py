"""Travel-time model: straight-line distance scaled to road distance at an urban average speed."""
import math

ROAD_FACTOR = 1.3  # road distance / straight-line distance
AVERAGE_SPEED_KMH = 30.0
STOP_OVERHEAD_MINUTES = 5  # parking, walking to the site, signing in


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def travel_minutes(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    km = haversine_km(lat1, lon1, lat2, lon2)
    if km < 0.05:
        return 0
    return math.ceil(km * ROAD_FACTOR / AVERAGE_SPEED_KMH * 60) + STOP_OVERHEAD_MINUTES

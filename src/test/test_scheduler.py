from datetime import datetime

from src.utils.schedule_store import compute_next_run, mark_task_ran, normalize_task


def test_once_schedule_skips_past_time():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = normalize_task(
        {
            "title": "Past",
            "prompt": "run",
            "schedule_type": "once",
            "run_at": "2026-04-29T09:59:00",
        },
        now=now,
    )

    assert task is not None
    assert task["enabled"] is False
    assert task["next_run_at"] == ""


def test_once_schedule_keeps_future_time():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = normalize_task(
        {
            "title": "Future",
            "prompt": "run",
            "schedule_type": "once",
            "run_at": "2026-04-29T10:30:00",
        },
        now=now,
    )

    assert task is not None
    assert task["enabled"] is True
    assert task["next_run_at"] == "2026-04-29T10:30:00"


def test_daily_schedule_rolls_to_tomorrow_after_time_passed():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = {"schedule_type": "daily", "time": "09:30"}

    assert compute_next_run(task, now=now) == datetime(2026, 4, 30, 9, 30, 0)


def test_daily_schedule_uses_today_when_future():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = {"schedule_type": "daily", "time": "18:45"}

    assert compute_next_run(task, now=now) == datetime(2026, 4, 29, 18, 45, 0)


def test_weekly_schedule_selects_nearest_future_weekday():
    now = datetime(2026, 4, 29, 10, 0, 0)  # Wednesday
    task = {"schedule_type": "weekly", "time": "09:00", "weekdays": [2, 4]}

    assert compute_next_run(task, now=now) == datetime(2026, 5, 1, 9, 0, 0)


def test_weekly_schedule_can_use_same_day_future_time():
    now = datetime(2026, 4, 29, 10, 0, 0)  # Wednesday
    task = {"schedule_type": "weekly", "time": "12:00", "weekdays": [2]}

    assert compute_next_run(task, now=now) == datetime(2026, 4, 29, 12, 0, 0)


def test_interval_schedule_skips_missed_intervals():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = {
        "schedule_type": "interval",
        "interval_minutes": 30,
        "created_at": "2026-04-29T08:10:00",
    }

    assert compute_next_run(task, now=now) == datetime(2026, 4, 29, 10, 10, 0)


def test_mark_task_ran_disables_once_task():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = {
        "id": "x",
        "title": "Once",
        "prompt": "run",
        "schedule_type": "once",
        "enabled": True,
        "run_at": "2026-04-29T10:00:00",
        "next_run_at": "2026-04-29T10:00:00",
    }

    updated = mark_task_ran(task, now=now)

    assert updated["enabled"] is False
    assert updated["last_run_at"] == "2026-04-29T10:00:00"
    assert updated["next_run_at"] == ""


def test_pet_scheduler_metadata_is_preserved():
    now = datetime(2026, 4, 29, 10, 0, 0)
    task = normalize_task(
        {
            "title": "副宠：整理员",
            "prompt": "run",
            "schedule_type": "interval",
            "interval_minutes": 30,
            "source": "pet",
            "pet_id": "pet-123",
        },
        now=now,
    )

    assert task is not None
    assert task["source"] == "pet"
    assert task["pet_id"] == "pet-123"

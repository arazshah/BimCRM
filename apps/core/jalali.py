"""Jalali (شمسی) month arithmetic for reports and installment schedules. Dates stay Gregorian in the DB."""

import datetime

import jdatetime

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _month_start(year: int, month: int) -> datetime.date:
    while month > 12:
        year, month = year + 1, month - 12
    while month < 1:
        year, month = year - 1, month + 12
    return jdatetime.date(year, month, 1).togregorian()


def month_bounds(day: datetime.date, offset: int = 0) -> tuple[datetime.date, datetime.date, str]:
    """[start, end) of the Jalali month containing `day`, shifted by `offset` months, plus its label."""
    j = jdatetime.date.fromgregorian(date=day)
    year, month = j.year, j.month + offset
    while month > 12:
        year, month = year + 1, month - 12
    while month < 1:
        year, month = year - 1, month + 12
    start = _month_start(year, month)
    end = _month_start(year, month + 1)
    return start, end, f"{MONTHS[month - 1]} {str(year).translate(_FA)}"


def add_months(day: datetime.date, months: int) -> datetime.date:
    """Same Jalali day-of-month `months` later, clamped to the month's length (31 Shahrivar -> 30 Mehr)."""
    j = jdatetime.date.fromgregorian(date=day)
    year, month = j.year, j.month + months
    while month > 12:
        year, month = year + 1, month - 12
    for d in range(j.day, 0, -1):
        try:
            return jdatetime.date(year, month, d).togregorian()
        except ValueError:
            continue
    raise ValueError("invalid date")

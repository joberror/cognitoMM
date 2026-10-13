import pytest
from features.statistics import format_percentage, format_number

def test_format_percentage():
    # Happy paths
    assert format_percentage(5, 10) == "50.0%"
    assert format_percentage(1, 3) == "33.3%"
    assert format_percentage(2, 3) == "66.7%"
    assert format_percentage(10, 10) == "100.0%"

    # Edge cases
    assert format_percentage(0, 10) == "0.0%"

    # Division by zero
    assert format_percentage(1, 0) == "0.0%"
    assert format_percentage(0, 0) == "0.0%"

def test_format_number():
    # Happy paths
    assert format_number(1000) == "1,000"
    assert format_number(1234567) == "1,234,567"
    assert format_number(10) == "10"

    # Negative numbers
    assert format_number(-10) == "-10"
    assert format_number(-1000) == "-1,000"

    # Floating point numbers
    assert format_number(1000.5) == "1,000.5"
    assert format_number(-1000.5) == "-1,000.5"

    # Edge cases
    assert format_number(0) == "0"
    assert format_number(None) == "0"
    assert format_number("") == "0"
    assert format_number(False) == "0"

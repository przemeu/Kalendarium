# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask web application for tracking and analyzing football/soccer match statistics for "Arka" team. The application provides comprehensive match data analysis, filtering capabilities, and statistical insights.

## Architecture

- **Backend**: Flask web application (`app.py`)
- **Database**: SQLite database (`Kalendarium.db`) with match data
- **Frontend**: HTML templates with Jinja2 templating (`templates/`)
- **Static Assets**: CSS styling (`static/styles.css`)

### Core Components

- `app.py`: Main Flask application with all routes, database operations, and statistical calculations
- `Kalendarium.db`: SQLite database containing match records in `Mecze` table
- Templates:
  - `base.html`: Base template with common layout
  - `index.html`: Main filter interface
  - `results.html`: Match results and statistics display
  - `details.html`: Individual match details
- `static/styles.css`: Application styling

## Database Schema

The `Mecze` table contains match data with columns including:
- `Id`: Primary key
- `Sezon`: Season
- `Przeciwnik`: Opponent
- `Liga`: League
- `Miejsce`: Venue (Dom/Wyjazd - Home/Away)
- `Wynik`: Score (format "X:Y")
- `Strzelcy`: Goal scorers
- `Full Date`: Match date
- `Frekwencja`: Attendance

## Key Features

1. **Match Filtering**: Filter matches by season, opponent, league, venue, date ranges, scorers
2. **Statistical Analysis**: Calculate streaks, home/away performance, top scorers
3. **Data Export**: Export filtered results to Excel
4. **Match Details**: Detailed view of individual matches with lineups

## Running the Application

```bash
python app.py
```

Or use the batch file:
```bash
./run_flask.bat
```

The application runs in debug mode by default on Flask's development server.

## Dependencies

The application requires:
- Flask
- pandas (for Excel export functionality)
- sqlite3 (built-in Python module)

A requirements file is available in `Socios/requirements.txt` containing:
- flask
- pillow
- gunicorn

## Development Notes

- No test framework is currently configured
- No linting or type checking tools are set up
- The application uses SQLite with direct SQL queries (no ORM)
- Statistical calculations are performed in Python rather than SQL for complex metrics
- Match data includes comprehensive streak calculations (winning, scoring, clean sheets, unbeaten)
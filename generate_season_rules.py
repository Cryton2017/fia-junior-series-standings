import os
import json
import re

FALLBACK_DISTANCES = {
    "f1": {"feature": "~305.000 km", "sprint": "~100.000 km"},
    "f2": {"feature": "~170.000 km", "sprint": "~120.000 km"},
    "f3": {"feature": "45 Mins",      "sprint": "40 Mins"} 
}

def extract_laps_from_results(file_path):
    """Parses result files to find the total laps completed by the winner."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            if isinstance(data, list) and len(data) > 0:
                for driver in data:
                    if "laps" in driver and str(driver["laps"]).isdigit():
                        return int(driver["laps"])
            
            elif isinstance(data, dict):
                # Jolpi / Ergast standard response structure
                try:
                    results = data["MRData"]["RaceTable"]["Races"][0]["Results"]
                    return int(results[0]["laps"])
                except (KeyError, IndexError, TypeError):
                    pass
                
                # Direct results list variants
                for key in ["results", "Results"]:
                    if key in data and isinstance(data[key], list) and len(data[key]) > 0:
                        laps_val = data[key][0].get("laps")
                        if laps_val and str(laps_val).isdigit():
                            return int(laps_val)
                            
                if "laps" in data and str(data["laps"]).isdigit():
                    return int(data["laps"])
    except Exception:
        pass
    
    return "TBC"

def get_circuit_length(circuit_slug, circuits_data):
    """Extracts numerical circuit length in km from circuits.json."""
    try:
        stats = circuits_data.get(circuit_slug, {})
        length_val = stats.get("length") or stats.get("length_km") or 0
        match = re.search(r"(\d+\.\d+|\d+)", str(length_val))
        if match:
            return float(match.group(1))
    except Exception:
        pass
    return None

def format_season_rules_json(data):
    """Serializes the season rules dictionary with each series kept on a single line."""
    lines = ["{"]
    circuits = list(data.keys())
    for i, circuit in enumerate(circuits):
        lines.append(f'  "{circuit}": {{')
        series_keys = list(data[circuit].keys())
        for j, s_key in enumerate(series_keys):
            item = data[circuit][s_key]
            
            # Format keys in logical order
            ordered_keys = ["featureLaps", "featureDistance", "hasSprint"]
            if item.get("hasSprint"):
                if "sprintLaps" in item:
                    ordered_keys.append("sprintLaps")
                if "sprintDistance" in item and item["sprintDistance"] is not None:
                    ordered_keys.append("sprintDistance")
            
            for k in item:
                if k not in ordered_keys:
                    ordered_keys.append(k)
                    
            parts = [f'"{k}": {json.dumps(item[k])}' for k in ordered_keys]
            inner_str = "{ " + ", ".join(parts) + " }"
            comma = "," if j < len(series_keys) - 1 else ""
            lines.append(f'    "{s_key}": {inner_str}{comma}')
            
        close_circuit_comma = "," if i < len(circuits) - 1 else ""
        lines.append(f'  }}{close_circuit_comma}')
    lines.append("}\n")
    return "\n".join(lines)

def generate_historical_rules(db_path="db"):
    # Allow execution from root or inside the db directory
    if not os.path.exists(db_path):
        if os.path.exists("circuits.json") or any(d.isdigit() for d in os.listdir(".")):
            db_path = "."
        else:
            print(f"Directory '{db_path}' not found.")
            return

    circuits_data = {}
    circuit_stats_path = os.path.join(db_path, "circuits.json")
    if not os.path.exists(circuit_stats_path):
        circuit_stats_path = "circuits.json"
        
    if os.path.exists(circuit_stats_path):
        with open(circuit_stats_path, 'r', encoding='utf-8') as f:
            circuits_data = json.load(f)
            print(f"Loaded {len(circuits_data)} tracks from {circuit_stats_path}")
    else:
        print(f"Warning: circuits.json not found at {circuit_stats_path}")

    for year_folder in sorted(os.listdir(db_path)):
        year_path = os.path.join(db_path, year_folder)
        
        if not os.path.isdir(year_path) or not year_folder.isdigit():
            continue
            
        race_year = int(year_folder)
        season_rules = {}

        # Load existing rules if present to preserve custom/manual entries
        existing_rules = {}
        out_path = os.path.join(year_path, "season_rules.json")
        alt_path = os.path.join(year_path, "seasonRules.json")
        
        active_read_path = out_path if os.path.exists(out_path) else (alt_path if os.path.exists(alt_path) else None)
        if active_read_path:
            try:
                with open(active_read_path, 'r', encoding='utf-8') as f:
                    existing_rules = json.load(f)
            except Exception as e:
                print(f"Could not read existing rules at {active_read_path}: {e}")

        for series in ["f1", "f2", "f3"]:
            series_path = os.path.join(year_path, series)
            if not os.path.isdir(series_path):
                continue
                
            # 1. Load series-level calendar.json or schedule.json if available
            series_calendar = {}
            for cal_name in ["calendar.json", "schedule.json"]:
                cal_file = os.path.join(series_path, cal_name)
                if os.path.exists(cal_file):
                    try:
                        with open(cal_file, 'r', encoding='utf-8') as f:
                            cal_content = json.load(f)
                            races = cal_content.get("races", []) if isinstance(cal_content, dict) else (cal_content if isinstance(cal_content, list) else [])
                            for r in races:
                                if isinstance(r, dict) and "round" in r:
                                    r_key = str(r["round"]).lstrip("0") or "0"
                                    series_calendar[r_key] = r
                    except Exception as e:
                        print(f"Error reading {cal_file}: {e}")
                    break

            # 2. Identify round folders
            round_folders = [d for d in os.listdir(series_path) if os.path.isdir(os.path.join(series_path, d))]
            
            targets = []
            if round_folders:
                for rf in round_folders:
                    targets.append((rf, os.path.join(series_path, rf)))
            elif series_calendar:
                for r_key in series_calendar:
                    targets.append((r_key, None))

            for round_folder, round_path in targets:
                r_key = str(round_folder).lstrip("0") or "0"
                race_obj = series_calendar.get(r_key)

                # Fallback: Check if round folder contains calendar.json or schedule.json
                if round_path:
                    for cand_name in ["calendar.json", "schedule.json"]:
                        cand_file = os.path.join(round_path, cand_name)
                        if os.path.exists(cand_file):
                            try:
                                with open(cand_file, 'r', encoding='utf-8') as f:
                                    r_data = json.load(f)
                                    if isinstance(r_data, dict):
                                        if "races" in r_data:
                                            for r in r_data["races"]:
                                                if str(r.get("round", "")).lstrip("0") == r_key:
                                                    race_obj = r
                                                    break
                                        elif "slug" in r_data or "circuitId" in r_data:
                                            race_obj = r_data
                            except Exception:
                                pass
                            break

                circuit_slug = None
                has_sprint = False
                feature_laps = "TBC"
                sprint_laps = "TBC"

                if race_obj:
                    circuit_slug = race_obj.get("slug") or race_obj.get("circuitId")
                    sessions = race_obj.get("sessions", {})
                    if any("sprint" in k.lower() and "qual" not in k.lower() for k in sessions.keys()):
                        has_sprint = True

                # Sprints did not exist in F1 before 2021
                if series == "f1" and race_year < 2021:
                    has_sprint = False

                # Extract laps from actual results files
                if round_path:
                    for filename in ["race.json", "feature.json", "results.json", "feature_race.json", "race_results.json"]:
                        file_path = os.path.join(round_path, filename)
                        if os.path.exists(file_path):
                            laps = extract_laps_from_results(file_path)
                            if laps != "TBC":
                                feature_laps = laps
                                break

                    for filename in ["sprint.json", "sprint_race.json", "sprint_results.json"]:
                        file_path = os.path.join(round_path, filename)
                        if os.path.exists(file_path):
                            laps = extract_laps_from_results(file_path)
                            if laps != "TBC":
                                sprint_laps = laps
                                has_sprint = True
                                break

                if not circuit_slug:
                    continue

                circuit_slug = circuit_slug.lower()
                c_length = get_circuit_length(circuit_slug, circuits_data)

                # Compute distance to 3 decimal places
                if feature_laps != "TBC" and c_length is not None:
                    feature_dist_str = f"{(feature_laps * c_length):.3f} km"
                else:
                    feature_dist_str = FALLBACK_DISTANCES[series]["feature"]

                if has_sprint:
                    if sprint_laps != "TBC" and c_length is not None:
                        sprint_dist_str = f"{(sprint_laps * c_length):.3f} km"
                    else:
                        sprint_dist_str = FALLBACK_DISTANCES[series]["sprint"]
                else:
                    sprint_dist_str = None

                if circuit_slug not in season_rules:
                    season_rules[circuit_slug] = {}

                rule_entry = {
                    "featureLaps": feature_laps,
                    "featureDistance": feature_dist_str,
                    "hasSprint": has_sprint
                }
                if has_sprint:
                    rule_entry["sprintLaps"] = sprint_laps
                    rule_entry["sprintDistance"] = sprint_dist_str

                season_rules[circuit_slug][series] = rule_entry

        # Merge with existing data so manual additions (like Madrid 2026) are preserved
        final_data = {}
        for c_slug, c_series_dict in existing_rules.items():
            final_data[c_slug] = dict(c_series_dict)

        for c_slug, s_dict in season_rules.items():
            if c_slug not in final_data:
                final_data[c_slug] = s_dict
            else:
                for s_name, s_rule in s_dict.items():
                    if s_name not in final_data[c_slug]:
                        final_data[c_slug][s_name] = s_rule
                    else:
                        existing_entry = final_data[c_slug][s_name]
                        if s_rule["featureLaps"] != "TBC":
                            existing_entry["featureLaps"] = s_rule["featureLaps"]
                            existing_entry["featureDistance"] = s_rule["featureDistance"]
                        elif "featureLaps" not in existing_entry:
                            existing_entry["featureLaps"] = "TBC"
                            existing_entry["featureDistance"] = s_rule["featureDistance"]

                        if s_rule["hasSprint"]:
                            existing_entry["hasSprint"] = True
                            if s_rule.get("sprintLaps") != "TBC":
                                existing_entry["sprintLaps"] = s_rule["sprintLaps"]
                                existing_entry["sprintDistance"] = s_rule.get("sprintDistance")
                            elif "sprintLaps" not in existing_entry:
                                existing_entry["sprintLaps"] = "TBC"
                                if "sprintDistance" in s_rule:
                                    existing_entry["sprintDistance"] = s_rule["sprintDistance"]

        if final_data:
            formatted_json = format_season_rules_json(final_data)
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(formatted_json)
            print(f"Saved: {out_path} ({len(final_data)} circuits)")
            
            # Keep seasonRules.json in sync if it exists in the directory
            if os.path.exists(alt_path):
                with open(alt_path, 'w', encoding='utf-8') as f:
                    f.write(formatted_json)

if __name__ == "__main__":
    generate_historical_rules()
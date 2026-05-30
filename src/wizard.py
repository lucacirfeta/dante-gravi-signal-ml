import argparse
import sys
import subprocess
import os
from pathlib import Path


def get_recent_sessions():
    """Retrieve a list of recent session IDs from data/runs."""
    try:
        runs_dir = Path("data/runs")
        if not runs_dir.exists():
            return []
        runs = []
        for run_path in runs_dir.iterdir():
            if run_path.is_dir():
                for session_path in run_path.iterdir():
                    if session_path.is_dir():
                        runs.append(session_path.name)
        # Sort in reverse chronological order (newest first)
        return sorted(runs, reverse=True)
    except Exception:
        return []


def prompt_bool(prompt: str) -> bool:
    """Prompt the user for a boolean yes/no response."""
    while True:
        resp = input(prompt + " [y/N]: ").strip().lower()
        if not resp or resp in ('n', 'no'):
            return False
        if resp in ('y', 'yes'):
            return True


def run_wizard(parser: argparse.ArgumentParser):
    """Run the interactive CLI wizard."""
    print("=" * 50)
    print(" Gravi-Signal-ML Interactive Wizard ")
    print("=" * 50)

    subparsers_action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    if not subparsers_action:
        print("Nessun subcommand disponibile.")
        return

    choices = subparsers_action.choices

    # Extract help strings
    help_strings = {}
    for a in subparsers_action._choices_actions:
        help_strings[a.dest] = a.help

    groups = {
        "Acquisizione": ["fetch", "scan", "scan-extended", "fetch-raw", "scan-live"],
        "Pipeline ML": ["reprocess-spectrograms", "encode", "cluster", "report", "full-analysis",
                        "full-analysis-report"],
        "Analisi": ["crosscheck", "morphcheck", "timeslide", "stability", "ablation", "benchmark-clustering",
                    "last-gps"],
        "Riferimento": ["build-reference", "build-indomain-reference", "validate-reference", "calibrate-threshold",
                        "calibrate-loglikelihood"]
    }

    # Flatten categories to maintain order
    ordered_commands = []
    for cat, cmds in groups.items():
        for c in cmds:
            if c in choices:
                ordered_commands.append((cat, c))

    # If there are any commands that are not in the predefined groups, add them to "Altro"
    grouped_cmds = {c for cmds in groups.values() for c in cmds}
    other_cmds = [c for c in choices if c not in grouped_cmds and c != "help"]
    if other_cmds:
        for c in other_cmds:
            ordered_commands.append(("Altro", c))

    recent_sessions = get_recent_sessions()

    while True:
        print("\nQuale operazione vuoi eseguire?")
        idx = 1
        cmd_map = {}
        current_cat = None
        for cat, cmd in ordered_commands:
            if cat != current_cat:
                print(f"\n--- {cat} ---")
                current_cat = cat

            desc = help_strings.get(cmd, "")
            print(f" {idx}) {cmd:<25} - {desc}")
            cmd_map[str(idx)] = cmd
            idx += 1

        choice = input("\nScelta (numero) [Invio per uscire]: ").strip()
        if not choice:
            break

        if choice not in cmd_map:
            print("Scelta non valida.")
            continue

        selected_cmd = cmd_map[choice]
        subparser = choices[selected_cmd]

        print(f"\nConfigurazione comando: {selected_cmd}")
        print("-" * 40)

        args_list = []
        smart_defaults = {}
        if selected_cmd == "morphcheck":
            print("\n  [Smart Default] Compilazione automatica dei path per morphcheck.")
            if prompt_bool("  Vuoi usare una session_id per generare in automatico i percorsi?"):
                if recent_sessions:
                    print("  Suggerimenti recenti per session_id:")
                    for i, s in enumerate(recent_sessions[:5], 1):
                        print(f"    {i}) {s}")
                sess_input = input("  > session_id (numero o stringa): ").strip()
                if sess_input.isdigit() and 1 <= int(sess_input) <= min(5, len(recent_sessions)):
                    sess_id = recent_sessions[int(sess_input) - 1]
                else:
                    sess_id = sess_input
                det = input("  > detector (es. h1): ").strip().lower()
                run_opt = input("  > run (es. o4a) [default: o4a]: ").strip().lower() or "o4a"

                if sess_id and det:
                    base_path = f"data/runs/{run_opt}/{sess_id}"
                    smart_defaults = {
                        "embeddings": f"{base_path}/embeddings/{run_opt}_{det}.npy",
                        "report": f"{base_path}/clusters/{det}/cluster_report.json",
                        "reference": "data/reference/indomain_index.npz",
                        "output": f"{base_path}/morphcheck/{det}/indomain_index.json",
                        "run": run_opt.capitalize() if run_opt[0].isalpha() else run_opt
                    }

        for action in subparser._actions:
            if action.dest == 'help':
                continue

            name = action.option_strings[0] if action.option_strings else action.dest
            desc = action.help or ""
            is_bool = isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction))
            is_required = action.required
            default = smart_defaults.get(action.dest, action.default)

            # Show default clearly for boolean
            if is_bool:
                val = prompt_bool(f"{name} ({desc})")
                if val:
                    args_list.append(name)
            else:
                type_func = action.type
                choices_list = action.choices

                prompt_text = f"{name}"
                if is_required and action.dest not in smart_defaults:
                    prompt_text += " (Obbligatorio)"
                if default is not None:
                    prompt_text += f" [default: {default}]"

                if choices_list:
                    prompt_text += f"\n  Scelte disponibili:\n"
                    for i, c in enumerate(choices_list, 1):
                        prompt_text += f"    {i}) {c}\n"
                elif type_func:
                    type_name = getattr(type_func, '__name__', str(type_func))
                    prompt_text += f" [Tipo: {type_name}]"

                if name == "--session-id" and recent_sessions:
                    prompt_text += f"\n  Suggerimenti recenti:\n"
                    for i, s in enumerate(recent_sessions[:5], 1):
                        prompt_text += f"    {i}) {s}\n"

                prompt_text += f"  Descrizione: {desc}\n  > "

                while True:
                    val = input(prompt_text).strip()

                    if name == "--session-id" and recent_sessions and val.isdigit():
                        idx = int(val)
                        if 1 <= idx <= min(5, len(recent_sessions)):
                            val = recent_sessions[idx - 1]

                    if choices_list and val.isdigit():
                        idx = int(val)
                        if 1 <= idx <= len(choices_list):
                            val = str(choices_list[idx - 1])
                    if not val:
                        if action.dest in smart_defaults:
                            if action.option_strings:
                                args_list.extend([name, str(default)])
                            else:
                                args_list.append(str(default))
                            break
                        elif default is not None:
                            # Not provided, but has default -> argparse will handle it
                            break
                        elif is_required:
                            print("Questo parametro è obbligatorio.")
                            continue
                        else:
                            # Not required, no default -> just skip
                            break
                    else:
                        # Validate choices
                        if choices_list and val not in [str(c) for c in choices_list]:
                            print(
                                f"  [!] Valore non valido. Inserisci un numero da 1 a {len(choices_list)} oppure il nome esatto.")
                            continue

                        # Validate type
                        if type_func:
                            try:
                                type_func(val)
                            except Exception:
                                type_name = getattr(type_func, '__name__', str(type_func))
                                print(f"  [!] Errore: il valore deve essere di tipo {type_name}.")
                                continue

                        if action.option_strings:
                            args_list.extend([name, val])
                        else:
                            args_list.append(val)
                        break

        # Check for GWPY_CACHE smart default explicitly if running a fetch/scan operation
        env = os.environ.copy()
        if selected_cmd in ["fetch", "scan", "scan-extended", "fetch-raw", "scan-live"]:
            if "GWPY_CACHE" not in env:
                print("\n  [Smart Default] GWPY_CACHE non è impostato.")
                if prompt_bool("  Vuoi abilitare la cache locale per i download GWOSC?"):
                    env["GWPY_CACHE"] = "1"

        full_cmd = [sys.executable, sys.argv[0], selected_cmd] + args_list
        print("\nRiepilogo comando:")
        print(" " + " ".join(full_cmd))
        if "GWPY_CACHE" in env and "GWPY_CACHE" not in os.environ:
            print(" (Con GWPY_CACHE=1)")

        if prompt_bool("\nConfermi l'esecuzione?"):
            print("\nEsecuzione in corso...\n")
            try:
                subprocess.run(full_cmd, env=env)
            except Exception as e:
                print(f"Errore durante l'esecuzione: {e}")
        else:
            print("Operazione annullata.")

        if not prompt_bool("\nVuoi eseguire un'altra operazione?"):
            break

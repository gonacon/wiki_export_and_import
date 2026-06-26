#!/usr/bin/env python3
"""
Unified failures CLI: run export/import report tasks via subcommands.

Usage examples:
  python3 scripts/failures.py export report --top 200
  python3 scripts/failures.py export --run-all
  python3 scripts/failures.py import report --input path/to/import_failed.json
"""
import argparse
import sys
from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]

def run_module(modpath: str, argv=None):
    """Import module (from scripts.reports...) and call main() if present.

    modpath: e.g. 'scripts.reports.export.generate_failed_report'
    """
    try:
        # Ensure repo root is on sys.path so top-level package `scripts` can be imported
        try:
            repo_root_str = str(REPO_ROOT)
            if repo_root_str not in sys.path:
                sys.path.insert(0, repo_root_str)
        except Exception:
            pass

        mod = __import__(modpath, fromlist=['*'])
        if hasattr(mod, 'main'):
            return mod.main(argv)
        else:
            raise ImportError('module has no main()')
    except Exception:
        # fallback: try to run script file via subprocess
        # Attempt several candidate locations for legacy wrapper scripts
        name = Path(modpath.replace('.', '/')).name
        candidates = [
            REPO_ROOT / 'scripts' / (name + '.py'),
            REPO_ROOT / (name + '.py'),
            REPO_ROOT / Path(modpath.replace('.', '/')).with_suffix('.py')
        ]
        for script_file in candidates:
            try:
                if script_file.exists():
                    return subprocess.call([sys.executable, str(script_file)] + (argv or []))
            except Exception:
                continue
        # nothing found
        raise


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')

    # export group
    export_p = sub.add_parser('export', help='Export-related report commands')
    export_sub = export_p.add_subparsers(dest='action')

    export_report = export_sub.add_parser('report', help='Generate export HTML report')
    # allow --top to be optional; if omitted we will generate the full report by default
    export_report.add_argument('--top', type=int, default=None, help='Top N failures to include (omit to include all)')
    export_report.add_argument('--all', action='store_true', help='Include all failures (same as omitting --top)')
    export_report.add_argument('--out')
    export_report.add_argument('--run-all', action='store_true')

    export_agg = export_sub.add_parser('aggregate', help='Run aggregate')
    export_collect = export_sub.add_parser('collect', help='Run collect')
    export_top = export_sub.add_parser('top', help='Generate top CSV')
    export_top.add_argument('--top', type=int, default=100)
    export_top.add_argument('--out')

    # import group
    import_p = sub.add_parser('import', help='Import-related report commands')
    import_sub = import_p.add_subparsers(dest='action')
    import_report = import_sub.add_parser('report', help='Generate import report')
    import_report.add_argument('--input')
    import_report.add_argument('--out')

    # If no argv provided and the user ran the script without CLI args, enter interactive prompt mode
    interactive = False
    if argv is None and len(sys.argv) <= 1:
        interactive = True
        print('\nInteractive mode: build an export/import command via prompts (press Enter to cancel)')
        try:
            cmd = input('Command (export/import) [export]: ').strip() or 'export'
            if cmd not in ('export', 'import'):
                print('Unknown command:', cmd)
                return 1

            if cmd == 'export':
                action = input('Action (report/aggregate/collect/top) [report]: ').strip() or 'report'
                if action not in ('report', 'aggregate', 'collect', 'top'):
                    print('Unknown action:', action)
                    return 1
                argv = [cmd, action]
                if action == 'report':
                    top_choice = input('Limit results? Enter a number for top N, or type "all" for everything (default all): ').strip()
                    if top_choice and top_choice.lower() != 'all':
                        try:
                            n = int(top_choice)
                            argv += ['--top', str(n)]
                        except Exception:
                            print('Invalid number:', top_choice)
                            return 1
                    else:
                        # include explicit --all to make intention clear
                        argv += ['--all']
                    outp = input('Output path (leave empty for default): ').strip()
                    if outp:
                        argv += ['--out', outp]
                    run_all = input('Also run aggregate/collect/top before report? (y/N): ').strip().lower()
                    if run_all == 'y':
                        argv += ['--run-all']
                elif action == 'top':
                    topv = input('Top N to generate (default 100): ').strip() or '100'
                    argv += ['--top', topv]
                    outp = input('Output path (leave empty for default): ').strip()
                    if outp:
                        argv += ['--out', outp]
            else:
                # import
                action = input('Action (report) [report]: ').strip() or 'report'
                if action != 'report':
                    print('Unknown import action:', action)
                    return 1
                argv = ['import', 'report']
                inp = input('Input JSON path (leave empty for default): ').strip()
                if inp:
                    argv += ['--input', inp]
                outp = input('Output path (leave empty for default): ').strip()
                if outp:
                    argv += ['--out', outp]
        except EOFError:
            print('\nInput ended (EOF). Interactive input cancelled.')
            return 1
        except KeyboardInterrupt:
            print('\nInterrupted. Interactive input cancelled.')
            return 1

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1

    if args.cmd == 'export':
        if args.action == 'report':
            argv2 = []
            # Only pass --top if user explicitly requested a limit
            if getattr(args, 'top', None) is not None:
                argv2 += ['--top', str(args.top)]
            # If user requested --all, pass that flag
            if getattr(args, 'all', False):
                argv2 += ['--all']
            if args.out:
                # If user passed a directory (no .html suffix), treat it as --out-dir for newer report behavior
                outp = args.out
                if outp and not (outp.endswith('.html') or outp.endswith('.htm')):
                    argv2 += ['--out-dir', outp]
                else:
                    argv2 += ['--out', outp]
            if args.run_all:
                argv2 += ['--run-all']
            # Pre-check: ensure aggregate/collect/top are run if necessary
            try:
                # ensure utils available
                repo_root_str = str(REPO_ROOT)
                if repo_root_str not in sys.path:
                    sys.path.insert(0, repo_root_str)
                from scripts._common import utils
                export_dir = utils.detect_export_dir()
                default_json = export_dir / 'failed_from_log.json'
                fallback_json = export_dir / 'failed_summary.json'
            except Exception:
                export_dir = None
                default_json = None
                fallback_json = None

            # Determine intended out_dir for report artifacts so pre-run steps can write there
            out_dir = None
            try:
                if getattr(args, 'out', None):
                    outp = args.out
                    if outp and not (outp.endswith('.html') or outp.endswith('.htm')):
                        out_dir = Path(outp)
                    else:
                        out_dir = Path(outp).parent
                else:
                    out_dir = export_dir / 'failed_report' if export_dir is not None else None
            except Exception:
                out_dir = None

            # candidate module paths
            agg_mod = 'scripts.reports.export.aggregate_log_failures'
            collect_mod = 'scripts.reports.export.collect_failed_pages'
            top_mod = 'scripts.reports.export.show_top_failures'

            # If failed_from_log.json is missing, try to run aggregation first
            if default_json is not None and not default_json.exists():
                try:
                    # Do not pass the report out_dir into the aggregation script.
                    # aggregate should detect the actual export dir (where migrate.log lives)
                    # and write its outputs there. generate_failed_report will copy artifacts
                    # into the report folder later.
                    print('No failed_from_log.json found; running aggregation...')
                    agg_args = []
                    rc = run_module(agg_mod, agg_args)
                    if rc != 0:
                        print('Aggregation returned non-zero rc:', rc)
                except Exception as e:
                    print('Aggregation failed:', e)

            # If run_all requested or failed_summary missing, run collect
            if (fallback_json is not None and not fallback_json.exists()) or getattr(args, 'run_all', False):
                try:
                    # Run collect without pointing it at the report folder so it reads
                    # inputs from the true export dir. Outputs will be written into the
                    # export dir and later copied into the report folder.
                    print('Running collect to generate failed_summary.json...')
                    coll_args = []
                    rc = run_module(collect_mod, coll_args)
                    if rc != 0:
                        print('Collect returned non-zero rc:', rc)
                except Exception as e:
                    print('Collect failed:', e)

            # If run_all requested, generate top CSV before report
            if getattr(args, 'run_all', False):
                try:
                    top_args = []
                    if getattr(args, 'top', None) is not None:
                        top_args = ['--top', str(args.top)]
                    else:
                        top_args = ['--top', '100']
                    print('Generating top CSV...')
                    # ask top script to write CSV into the report out_dir when known
                    if out_dir:
                        top_out = str((Path(out_dir) / 'top_failed_detailed.csv'))
                        top_args += ['--out', top_out]
                    rc = run_module(top_mod, top_args)
                    if rc != 0:
                        print('Top CSV generation returned non-zero rc:', rc)
                except Exception as e:
                    print('Top CSV generation failed:', e)

            # prevent generate_failed_report from auto-running aggregate/collect again
            if '--no-auto' not in argv2:
                argv2 += ['--no-auto']

            return run_module('scripts.reports.export.generate_failed_report', argv2)
        elif args.action == 'aggregate':
            return run_module('scripts.reports.export.aggregate_log_failures')
        elif args.action == 'collect':
            return run_module('scripts.reports.export.collect_failed_pages')
        elif args.action == 'top':
            argv2 = ['--top', str(args.top)]
            if args.out:
                argv2 += ['--out', args.out]
            return run_module('scripts.reports.export.show_top_failures', argv2)
        else:
            export_p.print_help()
            return 1

    if args.cmd == 'import':
        if args.action == 'report':
            argv2 = []
            if args.input:
                argv2 += ['--input', args.input]
            if args.out:
                argv2 += ['--out', args.out]
            return run_module('scripts.reports.import.generate_failed_report', argv2)
        else:
            import_p.print_help()
            return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())


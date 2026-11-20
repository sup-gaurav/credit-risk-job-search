"""Run configured GCC portal sources with disposable state; never publish production data.

Usage: python -m scanner.pilot --output audit/gcc_pilot.json
"""
import argparse
import tempfile
from pathlib import Path
from types import SimpleNamespace

from . import common, digest, pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--minutes', type=float, default=2)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent in (common.DATA.resolve(), common.STATE.resolve()):
        parser.error('pilot report must not overwrite production data or state')
    original = pipeline.DATA, pipeline.ARCHIVE, digest.DATA
    try:
        with tempfile.TemporaryDirectory(prefix='crjs-pilot-') as folder:
            pipeline.DATA = digest.DATA = Path(folder)
            pipeline.ARCHIVE = Path(folder) / 'archive.json'
            scan = pipeline.Scan(SimpleNamespace(max_queries=0))
            # Run the same portal selection, adapters, merge, scoring and digest path as the scheduled scan.
            with common.Budget(args.minutes * 60) as budget:
                scan.run_ats(budget)
            scan.merge()
            status = scan.publish()
            common.save_json(output, {
                'started': status['started'], 'finished': status['finished'],
                'duration_seconds': status['duration_seconds'], 'configured': len(scan.ats_status),
                'listings_read': sum(bool(s.get('listings_read')) for s in scan.ats_status.values()),
                'without_reported_gap': sum(s['state'] == 'ok' for s in scan.ats_status.values()),
                'blocked_or_unsupported': sum(s['state'] in ('blocked', 'no_adapter') for s in scan.ats_status.values()),
                'employers': scan.ats_status,
                'digest_ids': common.load_json(pipeline.DATA / 'digest.json')['ids'],
                'scope_note': 'Index observations, not total vacancies. Capped indexes and featured lists are coverage gaps.'
            }, indent=2)
            print(f'Pilot report: {output}')
    finally:
        pipeline.DATA, pipeline.ARCHIVE, digest.DATA = original


if __name__ == '__main__':
    main()
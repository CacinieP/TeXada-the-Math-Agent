"""Run preregistered transcription fixtures against a source or installed API.

No references are sent to inference. Preserve every response and strict verdict;
API checks do not constitute independent human or desktop UI acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import httpx
from structural_match import check_references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ocr-fixtures', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = Path(__file__).with_name('transcription_rc1.json')
    dataset = json.loads(fixture.read_text())
    client = httpx.Client(base_url=args.api, timeout=250, trust_env=False)

    def save(name, value):
        path = args.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    def call(path, text=None, image=None):
        start = time.monotonic()
        try:
            response = client.post(path, json={'text': text, 'render_mode': 'katex'}) \
                if image is None else client.post(
                    path, files={'image': (image.name, image.read_bytes(), 'image/png')},
                )
            row = {'http_status': response.status_code, 'response': response.json()}
            if row['response'].get('run_id'):
                row['run_log'] = client.get('/api/runs/' + row['response']['run_id']).json()
        except Exception as exc:
            row = {'http_status': None, 'error': str(exc)}
        row['elapsed_seconds'] = round(time.monotonic() - start, 3)
        return row

    def compare(row, refs):
        variants = [dict(latex=value, reference_id=str(i),
                         reference_source='source-authored before RC inference',
                         review_status='not independently human reviewed')
                    for i, value in enumerate(refs)]
        row['strict_structure'] = check_references(
            row.get('response', {}).get('latex'), variants,
        ).to_dict()

    save('status.json', client.get('/api/status').json())
    rows = []
    for entry in dataset['nl']:
        row = call('/api/agent', text=entry['input'])
        row.update(entry)
        compare(row, [entry['reference']])
        rows.append(row)
        save('nl/' + entry['id'] + '.json', row)
        save('nl.json', rows)
        print(entry['id'], row['http_status'], row['strict_structure']['status'],
              row.get('response', {}).get('stop_reason'), flush=True)

    excluded = []
    for text in dataset['outside_scope']:
        row = call('/api/agent', text=text)
        row['input'] = text
        excluded.append(row)
    save('outside-scope.json', excluded)

    ocr = []
    for entry in json.loads((args.ocr_fixtures / 'manifest.json').read_text()):
        image = args.ocr_fixtures / (entry['id'] + '.png')
        row = call('/api/ocr', image=image)
        row.update(case_id=entry['id'], source=entry['source'],
                   source_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        compare(row, entry.get('reference_alternatives', [entry['reference']]))
        ocr.append(row)
        save('ocr.json', ocr)
        print('OCR', entry['id'], row['http_status'],
              row.get('response', {}).get('stop_reason'), flush=True)

    completion = []
    for text in dataset['completion']:
        row = call('/api/complete', text=text)
        row['input'] = text
        completion.append(row)
        save('completion.json', completion)

    # Synthetic test-data decisions: adopt only an exact reference match.
    decisions = []
    eligible = [r for r in rows if r['strict_structure']['status'] == 'MATCH'
                and r.get('response', {}).get('valid') and r['response'].get('review')]
    for row, decision in zip(eligible[:2], ['accept', 'reject'], strict=False):
        review = row['response']['review']
        path = '/api/reviews/' + review['id'] + '/decision'
        binding = {key: review[key] for key in (
            'input_hash', 'parent_revision', 'candidate_hash', 'current_revision',
        )}
        stale = client.post(path, json=dict(binding, current_revision=999, decision=decision))
        applied = client.post(path, json=dict(binding, decision=decision))
        opposite = client.post(path, json=dict(
            binding, decision='reject' if decision == 'accept' else 'accept',
        ))
        decisions.append(dict(case_id=row['id'], decision=decision,
                              stale_status=stale.status_code, http_status=applied.status_code,
                              response=applied.json(), opposite_status=opposite.status_code))
    save('decisions.json', decisions)

    def summarize(items):
        results = [r.get('response', {}) for r in items]
        return dict(total=len(items), http_200=sum(r['http_status'] == 200 for r in items),
                    workflow_valid=sum(bool(r.get('valid')) for r in results),
                    nonempty=sum(bool(r.get('latex')) for r in results),
                    auto_committed=sum(bool(r.get('committed')) for r in results),
                    pending_review=sum(r.get('review', {}).get('status') == 'pending'
                                       for r in results if r.get('review')),
                    strict_structure=dict(Counter(r.get('strict_structure', {}).get(
                        'status', 'NOT_CHECKED') for r in items)),
                    stop_reasons=dict(Counter(r.get('stop_reason') for r in results)))

    summary = dict(dataset_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                   nl=summarize(rows), ocr=summarize(ocr), completion=summarize(completion),
                   outside_scope_422=sum(r['http_status'] == 422 for r in excluded),
                   outside_scope_total=len(excluded),
                   limitations='Synthetic OCR; strict structure is not accuracy. No independent '
                   'human adjudication, native desktop manual or Windows/Intel model acceptance.')
    integral = next(r.get('response', {}) for r in ocr if r['case_id'] == 'integral')
    summary['rc_engineering_gates'] = {
        'nl_transport_and_no_auto_commit': summary['nl']['http_200'] == 24
        and summary['nl']['auto_committed'] == 0,
        'nl_workflow_at_least_22': summary['nl']['workflow_valid'] >= 22,
        'nl_strict_match_at_least_20': summary['nl']['strict_structure'].get('MATCH', 0) >= 20,
        'scope_rejected': summary['outside_scope_422'] == 10,
        'ocr_no_auto_commit_and_integral_completed': summary['ocr']['auto_committed'] == 0
        and integral.get('valid') is True
        and integral.get('stop_reason') == 'human_review_required',
        'completion_no_answers': len(completion) == 6 and all(
            r['http_status'] == 200 and '\\placeholder' in r['response'].get('latex', '')
            for r in completion),
        'bound_decisions': len(decisions) == 2 and all(
            r['http_status'] == 200 and r['stale_status'] == 409 and r['opposite_status'] == 409
            and r['response'].get('status') == r['decision'] + 'ed'
            for r in decisions),
    }
    save('summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    client.close()


if __name__ == '__main__':
    main()

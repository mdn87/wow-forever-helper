"""Bounded sourced quest relationships, separate from observed completion."""

from copy import deepcopy
from urllib.parse import urlsplit

from .chat import ChatError

CHAIN_SCHEMA = {'type': 'object', 'additionalProperties': False,
    'properties': {
        'edition': {'type': 'string'}, 'summary': {'type': 'string'},
        'caveats': {'type': 'array', 'items': {'type': 'string'}},
        'nodes': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'properties': {'id': {'type': 'integer'}, 'title': {'type': 'string'},
                           'requires': {'type': 'array', 'items': {'type': 'integer'}},
                           'relation': {'type': 'string', 'enum': ['all', 'any', 'unknown']},
                           'sources': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['id', 'title', 'requires', 'relation', 'sources']}}},
    'required': ['edition', 'summary', 'caveats', 'nodes']}


def normalize_chain(raw, edition):
    def fail():
        raise ChatError('The quest chain is malformed, oversized, or for another edition. Retry research explicitly.')

    if not isinstance(raw, dict) or raw.get('edition') != edition or not isinstance(raw.get('summary'), str):
        fail()
    nodes, caveats = raw.get('nodes'), raw.get('caveats')
    if (not isinstance(nodes, list) or len(nodes) > 32 or not isinstance(caveats, list)
            or len(caveats) > 12 or any(not isinstance(c, str) for c in caveats)):
        fail()
    result = {'edition': edition, 'summary': raw['summary'][:3000], 'nodes': [],
              'caveats': [c[:1200] for c in caveats]}
    ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            fail()
        key, title, requirements, urls = node.get('id'), node.get('title'), node.get('requires'), node.get('sources')
        if (type(key) is not int or not 0 < key < 10_000_000 or key in ids
                or not isinstance(title, str) or not title.strip()
                or not isinstance(node.get('relation'), str)
                or node.get('relation') not in {'all', 'any', 'unknown'}
                or not isinstance(requirements, list) or len(requirements) > 16
                or any(type(i) is not int or not 0 < i < 10_000_000 for i in requirements)
                or not isinstance(urls, list) or len(urls) > 8 or any(not isinstance(u, str) for u in urls)):
            fail()
        ids.add(key)
        sources = []
        for url in urls:
            try:
                parsed = urlsplit(url)
                if (len(url) <= 2000 and not any(c.isspace() for c in url) and parsed.scheme == 'https'
                        and parsed.hostname and not parsed.username and not parsed.password):
                    sources.append(url)
            except ValueError:
                pass
        result['nodes'].append({'id': key, 'title': title[:300], 'requires': list(dict.fromkeys(requirements)),
                                'relation': node['relation'], 'sources': sources,
                                'evidence_state': 'Sourced claim; not independently verified' if sources else 'Unverified claim'})
    graph = {n['id']: n['requires'] for n in result['nodes']}
    missing = sorted({i for requirements in graph.values() for i in requirements if i not in ids})
    if missing:
        result['caveats'].append('Missing prerequisite details for quest IDs: ' + ', '.join(map(str, missing)))
    visiting, visited = set(), set()
    def cycle(key):
        if key in visiting:
            return True
        if key in visited:
            return False
        visiting.add(key)
        found = any(cycle(i) for i in graph.get(key, []) if i in graph)
        visiting.remove(key); visited.add(key)
        return found
    if any(cycle(key) for key in graph):
        result['caveats'].append('Dependency cycle found. The relationships are uncertain; no valid order is established.')
    if any(n['relation'] == 'unknown' for n in result['nodes']):
        result['caveats'].append('Some prerequisite relationships are uncertain: all-versus-any is unknown.')
    if any(not n['sources'] for n in result['nodes']) or not nodes:
        result['caveats'].append('Sources are missing for some or all claims. Research is incomplete and unverified.')
    return result


def annotate_chain(chain, report):
    result = deepcopy(chain)
    completed = set(report.get('completed_ids') or [])
    active = {q.get('id'): q.get('action') for q in report.get('plan', [])}
    for node in result['nodes']:
        key = node['id']
        node['observed'] = ('Completed in saved snapshot' if key in completed else
                            'Objectives done; turn-in unobserved' if active.get(key) == 'turn in' else
                            'In saved quest log' if key in active else 'Not observed; completion unknown')
    result['snapshot_warnings'] = list(report.get('warnings', []))
    if report.get('completion_coverage') != 'available':
        result['snapshot_warnings'].append('Completed-quest coverage is missing or truncated; absence proves nothing.')
    return result


def chain_text(chain):
    lines = [chain['edition'], chain['summary'], '', 'REPORTED RELATIONSHIPS AND SEPARATE SNAPSHOT OBSERVATIONS']
    for node in chain['nodes']:
        lines += ['', f"{node['id']} · {node['title']}", 'Snapshot: ' + node.get('observed', 'Not compared'),
                  'Claim: ' + node['evidence_state'],
                  'Prerequisites (' + node['relation'] + '): ' + (', '.join(map(str, node['requires'])) or 'None reported; not proof of none'),
                  'Next quests (reported): ' + (', '.join(str(n['id']) for n in chain['nodes'] if node['id'] in n['requires']) or 'Unknown'),
                  'Sources: ' + ('\n'.join(node['sources']) or 'Missing')]
    lines += ['', 'UNCERTAINTY'] + chain['caveats'] + chain.get('snapshot_warnings', [])
    return '\n'.join(lines)

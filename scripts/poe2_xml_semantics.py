"""Compare every XML section using PoB's actual XML parser semantics.

Its parser preserves literal attribute newlines and supports only named XML
entities. Standard XML parsers normalize those newlines and can conceal a lost
multi-line quest reward. Only known, uniquely keyed maps are order-normalized;
skill/gem sequences and repeated keys retain their order.
"""
import base64
from functools import lru_cache
from pathlib import Path
from lupa.luajit21 import LuaRuntime


@lru_cache(maxsize=1)
def _parser():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    source = Path(__file__).resolve().parents[1] / 'PathOfBuilding/runtime/lua/xml.lua'
    return runtime, runtime.execute(source.read_text())


def _tree_link(value):
    try:
        prefix, encoded = value.rsplit('/', 1)
        raw = base64.urlsafe_b64decode(encoded)
        if raw[:4] != b'\x00\x00\x00\x06':
            return value
        pos, groups = 6, []
        for width in (2, 2, 4):
            count = raw[pos]
            pos += 1
            end = pos + count * width
            if end > len(raw):
                return value
            groups.append(tuple(sorted(raw[i:i + width] for i in range(pos, end, width))))
            pos = end
        return (prefix, raw[:6], tuple(groups)) if pos == len(raw) else value
    except (ValueError, IndexError):
        return value


def canonical(source):
    _, parser = _parser()
    document = parser.ParseXML(source)
    if isinstance(document, tuple):
        raise ValueError('Native XML parse failed: ' + str(document[1]))
    if document is None or len(document) != 1 or document[1]['elem'] != 'PathOfBuilding2':
        raise ValueError('Expected one native PathOfBuilding2 document')

    def visit(node):
        if isinstance(node, str):
            return node
        tag = node['elem']
        attrs = dict(node['attrib'].items()) if node['attrib'] is not None else {}
        for key in ('nodes', 'strNodes', 'dexNodes', 'intNodes'):
            if key in attrs:
                attrs[key] = ','.join(sorted(attrs[key].split(',')))
        children = [visit(node[i]) for i in range(1, len(node) + 1)]
        if tag == 'URL':
            children = [_tree_link(c) if isinstance(c, str) and '/passive-skill-tree/' in c else c for c in children]
        if tag in ('ConfigSet', 'ItemSet') and all(isinstance(c, tuple) for c in children):
            keys = [(c[0], dict(c[1]).get('name')) for c in children]
            if all(name is not None for _, name in keys) and len(set(keys)) == len(keys):
                children.sort(key=repr)
        if tag == 'Calcs':
            # Native CalcsTab.Save emits a unique Input map, then ordered Sections.
            inputs, names = [], set()
            for index, child in enumerate(children):
                if isinstance(child, tuple) and child[0] == 'Input':
                    name = dict(child[1]).get('name')
                    if index != len(inputs) or name is None or name in names:
                        break
                    names.add(name)
                    inputs.append(child)
            else:
                children[:len(inputs)] = sorted(inputs, key=repr)
        if tag == 'PathOfBuilding2' and all(isinstance(c, tuple) for c in children):
            # Native Build sections are keyed by element name; pairs() can emit
            # them in another order after restarting the Lua runtime.
            keys = [c[0] for c in children]
            if len(set(keys)) == len(keys):
                children.sort(key=repr)
        return tag, tuple(sorted(attrs.items())), tuple(children)

    return visit(document[1])

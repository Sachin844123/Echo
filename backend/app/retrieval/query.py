"""Conservative local vocabulary correction; no query history or remote service."""

import re
import unicodedata


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.casefold()) if not unicodedata.combining(c))


def distance(left, right, maximum):
    if abs(len(left) - len(right)) > maximum:
        return maximum + 1
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char != other)))
        if min(current) > maximum:
            return maximum + 1
        previous = current
    return previous[-1]


def correct_query(session, value):
    connection = session.connection()
    connection.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS temp.echo_vocab USING fts5vocab(main, 'chunk_fts', 'row')")
    corrections = []
    replacements = {}
    # Bounded correction work for long or hostile queries. Acronyms are untouched.
    for match in list(re.finditer(r"\w+", value))[:24]:
        original = match.group()
        term = normalized(original)
        if term in replacements or not 5 <= len(term) <= 32 or not term.isalpha():
            continue
        if connection.exec_driver_sql("SELECT 1 FROM temp.echo_vocab WHERE term=?", (term,)).first():
            continue
        maximum = 1 if len(term) < 9 else 2
        prefix = term[:2]
        candidates = connection.exec_driver_sql(
            "SELECT term FROM temp.echo_vocab WHERE term>=? AND term<? AND length(term) BETWEEN ? AND ? ORDER BY term LIMIT 1001",
            (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1), len(term) - maximum, len(term) + maximum)).scalars().all()
        if len(candidates) > 1000:
            continue  # Ambiguous/unbounded vocabulary neighborhoods are never guessed.
        ranked = sorted((distance(term, candidate, maximum), candidate) for candidate in candidates)
        if ranked and ranked[0][0] <= maximum and (len(ranked) == 1 or ranked[1][0] > ranked[0][0]):
            replacements[term] = ranked[0][1]
            corrections.append({"from": original, "to": ranked[0][1]})
    effective = re.sub(r"\w+", lambda match: replacements.get(normalized(match.group()), match.group()), value)
    return effective, corrections

"""TWS execution revision markers; raw facts are never deleted or auto-replaced.

IBKR documents numeric changes after the final period as execution corrections.
Until a canonical economic revision resolver is verified, these facts require
reconciliation instead of being summed as independent fills or releasing cash.
"""


def correction_markers(executions):
    facts=list(executions);families={};unresolved=set()
    for fact in facts:
        identity=str(fact.get('exec_id',''))
        family,dot,revision=identity.rpartition('.')
        if not dot or not family or not revision.isascii() or not revision.isdecimal():continue
        families.setdefault(family,set()).add(identity)
        if int(revision)>1:unresolved.add(identity)
    for identities in families.values():
        if len(identities)>1:unresolved.update(identities)
    return unresolved

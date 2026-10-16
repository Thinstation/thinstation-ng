// Confirmation display and button state use one tested rule. No API calls here.
export function deletionPhrase(rows = []) {
  if (!Array.isArray(rows) || !rows.length || rows.some(row => typeof row?.name !== 'string' || !row.name)) return '';
  return rows.length === 1 ? 'DELETE ' + rows[0].name : 'DELETE ' + rows.length + ' ITEMS';
}

export function matchesDeletionPhrase(value, expected) {
  if (!expected || typeof value !== 'string') return false;
  // Normalize only formatting and the action words, never the target name.
  const match = /^delete\s+(.+)$/i.exec(value.trim());
  if (!match) return false;
  let target = match[1];
  if (/^DELETE [1-9][0-9]* ITEMS$/.test(expected)) {
    const bulk = /^([1-9][0-9]*)\s+items$/i.exec(target);
    if (!bulk) return false;
    target = bulk[1] + ' ITEMS';
  }
  return 'DELETE ' + target === expected;
}

export function confirmationState(confirmation, acknowledged, phrase, blocked = false) {
  const action = confirmation?.action;
  const rows = confirmation?.rows;
  const deleting = action === 'delete';
  const expected = deleting ? deletionPhrase(rows) : '';
  const phraseMatches = deleting ? matchesDeletionPhrase(phrase, expected) : true;
  let message = '';
  if (!Array.isArray(rows) || !rows.length || !['delete', 'update', 'rebuild'].includes(action) || (deleting && !expected)) {
    message = 'No valid operation is selected. Close this dialog and review the targets again.';
  } else if (blocked) {
    message = 'Wait for the current operation or inventory refresh to finish. Resolve any inventory error before continuing.';
  } else if (!acknowledged && deleting && !phraseMatches) {
    message = 'Check the review box and enter the full displayed confirmation phrase.';
  } else if (!acknowledged) {
    message = 'Check the review box to enable confirmation.';
  } else if (!phraseMatches) {
    message = phrase.trim() ? 'The confirmation text does not match. Include DELETE and the exact name or displayed item count.' : 'Enter the full displayed confirmation phrase.';
  }
  return {ready: !message, expected, phraseMatches,
    message: message || (deleting ? 'Confirmation complete. The Delete button is now enabled.' : 'Review acknowledged. You can confirm this operation.')};
}

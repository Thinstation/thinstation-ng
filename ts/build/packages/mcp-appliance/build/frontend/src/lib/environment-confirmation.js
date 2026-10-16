// One review acknowledgment for each exact selected operation. No API calls here.
export function confirmationState(confirmation, acknowledged, blocked = false) {
  const action = confirmation?.action;
  const rows = confirmation?.rows;
  let message = '';
  if (!Array.isArray(rows) || !rows.length || rows.some(row => typeof row?.name !== 'string' || !row.name.trim()) || !['delete', 'update', 'rebuild'].includes(action)) {
    message = 'No valid operation is selected. Close this dialog and review the targets again.';
  } else if (blocked) {
    message = 'Wait for the current operation or inventory refresh to finish. Resolve any inventory error before continuing.';
  } else if (acknowledged !== true) {
    message = 'Check the review box to enable confirmation.';
  }
  return {ready: !message,
    message: message || (action === 'delete' ? 'Review acknowledged. The Delete button is now enabled.' : 'Review acknowledged. You can confirm this operation.')};
}

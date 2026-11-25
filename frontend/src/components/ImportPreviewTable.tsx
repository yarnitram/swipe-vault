import type { ImportPreviewRow, ImportRowStatus } from '../api/types';
import { Badge } from './ui';

const statusTone: Record<ImportRowStatus, 'emerald' | 'rose' | 'amber' | 'violet'> = {
  valid: 'emerald',
  invalid: 'rose',
  duplicate_existing: 'amber',
  duplicate_in_file: 'violet',
};

const statusLabel: Record<ImportRowStatus, string> = {
  valid: 'valid',
  invalid: 'invalid',
  duplicate_existing: 'duplicate (existing)',
  duplicate_in_file: 'duplicate (in file)',
};

export function ImportStatusBadge({ status }: { status: ImportRowStatus }) {
  return <Badge tone={statusTone[status] ?? 'slate'}>{statusLabel[status] ?? status}</Badge>;
}

export default function ImportPreviewTable({
  rows,
  selected,
  onToggle,
  onToggleAll,
}: {
  rows: ImportPreviewRow[];
  selected: Set<number>;
  onToggle: (rowNumber: number) => void;
  onToggleAll: (checked: boolean) => void;
}) {
  const validRows = rows.filter((r) => r.status === 'valid');
  const allSelected = validRows.length > 0 && validRows.every((r) => selected.has(r.row_number));
  return (
    <div className="max-h-[55vh] overflow-auto rounded-md border border-slate-200">
      <table className="table-base">
        <thead className="sticky top-0">
          <tr>
            <th className="w-8">
              <input
                type="checkbox"
                aria-label="Select all valid rows"
                checked={allSelected}
                disabled={validRows.length === 0}
                onChange={(e) => onToggleAll(e.target.checked)}
              />
            </th>
            <th>Row</th>
            <th>Status</th>
            <th>Network</th>
            <th>Offer ID</th>
            <th>Title</th>
            <th>Niche</th>
            <th>Vendor</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row_number} data-testid={`import-row-${r.row_number}`} className={r.status !== 'valid' ? 'bg-slate-50/60' : ''}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Select row ${r.row_number}`}
                  disabled={r.status !== 'valid'}
                  checked={selected.has(r.row_number)}
                  onChange={() => onToggle(r.row_number)}
                />
              </td>
              <td className="tabular-nums">{r.row_number}</td>
              <td>
                <ImportStatusBadge status={r.status} />
              </td>
              <td>{r.data.network || '—'}</td>
              <td>{r.data.external_offer_id || '—'}</td>
              <td className="max-w-xs break-words font-medium">{r.data.title || '—'}</td>
              <td>{r.data.niche || '—'}</td>
              <td>{r.data.vendor_name || '—'}</td>
              <td className="text-rose-700">
                {r.errors.length > 0 ? (
                  <ul className="list-inside list-disc text-xs">
                    {r.errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                ) : r.existing_offer_id ? (
                  <a className="link text-xs" href={`/offers/${r.existing_offer_id}`}>
                    existing offer
                  </a>
                ) : (
                  ''
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

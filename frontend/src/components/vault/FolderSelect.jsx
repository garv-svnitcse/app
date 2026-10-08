import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

// Radix Select can't use "" as an item value, so "no folder" gets a sentinel.
const UNFILED = "__unfiled__";

export default function FolderSelect({ value, onChange, folders, disabled }) {
  return (
    <Select value={value || UNFILED} onValueChange={(v) => onChange(v === UNFILED ? "" : v)} disabled={disabled}>
      <SelectTrigger data-testid="vault-folder-select"><SelectValue placeholder="Unfiled" /></SelectTrigger>
      <SelectContent>
        <SelectItem value={UNFILED}>Unfiled</SelectItem>
        {folders.map((f) => <SelectItem key={f.id} value={f.id}>{f.name}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

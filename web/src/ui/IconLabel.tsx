import type { LucideIcon } from 'lucide-react';
import './IconLabel.css';

export function IconLabel({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <span className="icon-label">
      <Icon size={20} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}

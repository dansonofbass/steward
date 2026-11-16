// jsdom has <dialog> but none of its behaviour: no showModal(), no close(), no close requests. This stands in for the
// parts Sheet uses, as the HTML spec describes them, so a test of a sheet sees what a browser does. Test-only.
//  - showModal() opens it as the newest modal, remembers what had focus and runs the focusing steps.
//  - close() closes it, gives focus back to what had it before (a modal always does) and fires close. A browser fires
//    close a task later; here it is at once, which Sheet doesn't depend on.
//  - requestClose(), and Escape when no key handler took it (preventDefault), fire a cancelable cancel at the newest
//    open modal, then close it unless cancel was prevented. Android's back gesture is the same close request.
//  - closedBy is left out on purpose, as in Safari: Sheet's own backdrop-tap code is what the tests exercise.

import { act } from '@testing-library/react';

const FOCUSABLE = '[autofocus], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]';
let modals: HTMLDialogElement[] = [];
const before = new WeakMap<HTMLDialogElement, Element | null>();

const topModal = () => [...modals].reverse().find((d) => d.isConnected && d.open) ?? null;

export function installDialog() {
  const proto = HTMLDialogElement.prototype as HTMLDialogElement & Record<string, unknown>;
  if (typeof proto.showModal === 'function' && !('stewardShim' in proto)) return;   // a jsdom that has it
  Object.defineProperty(proto, 'stewardShim', { value: true });
  Object.defineProperty(proto, 'open', {
    configurable: true,
    get(this: HTMLDialogElement) { return this.hasAttribute('open'); },
    set(this: HTMLDialogElement, v: boolean) { this.toggleAttribute('open', Boolean(v)); },
  });
  proto.show = function show(this: HTMLDialogElement) { this.setAttribute('open', ''); };
  proto.showModal = function showModal(this: HTMLDialogElement) {
    if (this.open) throw new DOMException('The dialog is already open.', 'InvalidStateError');
    if (!this.isConnected) throw new DOMException('The dialog is not in a document.', 'InvalidStateError');
    before.set(this, document.activeElement);
    this.setAttribute('open', '');
    modals.push(this);
    ((this.querySelector(FOCUSABLE) as HTMLElement | null) ?? this).focus();
  };
  proto.close = function close(this: HTMLDialogElement, value?: string) {
    if (!this.open) return;
    const wasModal = modals.includes(this);
    this.removeAttribute('open');
    modals = modals.filter((d) => d !== this);
    if (value !== undefined) this.returnValue = value;
    const prev = before.get(this);
    before.delete(this);
    if (wasModal && prev instanceof HTMLElement && prev.isConnected) prev.focus();
    this.dispatchEvent(new Event('close'));
  };
  proto.requestClose = function requestClose(this: HTMLDialogElement) {
    if (!this.open) return;
    if (this.dispatchEvent(new Event('cancel', { cancelable: true }))) this.close();
  };
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    topModal()?.requestClose();
  });
}

/** Android's back gesture, or Escape: a close request to the newest open modal dialog. */
export function closeRequest() {
  act(() => { topModal()?.requestClose(); });
}

/** A browser's close request with no user activation since the last one prevented: cancel can't be prevented, so the
 *  dialog closes anyway (the anti-abuse rule for repeated back presses). */
export function forcedCloseRequest() {
  const top = topModal();
  if (!top) return;
  act(() => {
    top.dispatchEvent(new Event('cancel', { cancelable: false }));
    top.close();
  });
}

export function forgetDialogs() {
  modals = [];
}

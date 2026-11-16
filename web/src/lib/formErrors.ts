// WEB-4: after a failed submit, focus goes to the first invalid field, so a screen reader reads its label, its invalid
// state and its error together (a field's error isn't a live region; one shown rather than changed isn't read). One
// watcher for every form: a submitted form is pending until the person types in it again, and an invalid field that
// appears while it is pending, at once or when the server answers, takes focus. Field asks for it when its error
// appears; a form that marks its own fields aria-invalid (Export, Targets) is caught by the check after the submit.

/** Forms submitted since the person last typed in them. */
const pending = new WeakSet<HTMLFormElement>();
let watching = false;

/** Focuses the form's first invalid field if the form was just submitted; true when it did. */
export function focusFirstInvalid(form: HTMLFormElement | null | undefined): boolean {
  if (!form || !pending.has(form)) return false;
  const first = form.querySelector<HTMLElement>('[aria-invalid="true"]');
  if (!first) return false;
  pending.delete(form);
  first.focus();
  return true;
}

/** Starts the watcher, once. The submit listener runs after the form's own handler (it bubbles to the document), and
 *  checks once React has rendered what the handler set: an error the same as last time renders nothing new, so Field
 *  alone wouldn't see it. */
export function watchSubmits() {
  if (watching || typeof document === 'undefined') return;
  watching = true;
  document.addEventListener('submit', (e) => {
    if (!(e.target instanceof HTMLFormElement)) return;
    const form = e.target;
    pending.add(form);
    queueMicrotask(() => { focusFirstInvalid(form); });
  });
  document.addEventListener('input', (e) => {
    const form = e.target instanceof Element ? e.target.closest('form') : null;
    if (form) pending.delete(form);
  }, true);
}

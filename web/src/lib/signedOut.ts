// What this tab and device forget when the person signs out, from the You menu or from Sign-in and devices. One list,
// so the two ways out can't drift apart. Device settings (theme, Swipe to sort, the swipe demo) stay.
import { forgetProfileOpened } from '../book/profileVisit';
import { clearJoy } from '../screens/accounts/joy';
import { clearKeptDraft } from '../screens/plan/planMemory';
import { forgetPersonPrefs } from './celebrations';

export function forgetSignedOut(): void {
  clearKeptDraft();     // the unsaved Plan moves and the saved note
  clearJoy();           // the net worth bracket and limits this device cheered (issue #6)
  forgetPersonPrefs();  // the next person starts from their own Celebrations and Sound
  forgetProfileOpened(); // the next person's Home can open their own Profile once (issue #30)
}

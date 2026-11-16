import { describe, expect, it } from 'vitest';
import { OLD_STEP_SECTION, PLAN_ITEM_SECTION, SECTION_NAME, SECTION_ORDER, SECTION_STEPS, sectionPath } from './profileSections';

describe('profile sections', () => {
  it('runs in JR order with the spec names and the server step keys', () => {
    expect(SECTION_ORDER.map((k) => SECTION_NAME[k])).toEqual(['You and your partner', 'Kids and college', 'Home and cars',
      'Social Security and Medicare', 'Banks and accounts']);
    expect(SECTION_STEPS.home).toEqual(['own', 'homes', 'mortgages', 'cars']);
  });
  it('builds addresses and maps the old ones', () => {
    expect(sectionPath('home')).toBe('/profile/home');
    expect(sectionPath('home', 'mortgages', 'plan')).toBe('/profile/home/mortgages?from=plan');
    expect([PLAN_ITEM_SECTION.mortgage, PLAN_ITEM_SECTION.earnings_spouse, PLAN_ITEM_SECTION.history]).toEqual(['home', 'benefits', undefined]);
    expect([OLD_STEP_SECTION.pay, OLD_STEP_SECTION.health]).toEqual(['you', 'benefits']);
  });
});

// What a Springform connection gives the account (backend connect.approve, hosted only).
// While the suite is free (config.free) no level is named.
export const springformOffer = (free: boolean) =>
  free
    ? 'A Springform install wants to use your GTD account.'
    : 'A Springform install wants to use your GTD account; it gets the highest limits for free.';
export const springformEmail = (free: boolean) =>
  free ? 'Email (confirm it to unlock everything)' : 'Email (confirm it to get the highest limits)';

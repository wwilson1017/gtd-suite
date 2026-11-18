// Simple Sites — the home page's prices: Free and Pro side by side, shown only where
// Pro is on sale (config.billing). Pro is bought inside the app, after starting free.
// simplification: the price and limits are text here, in PlanCard and in billing.PRICE;
// change them together.
const FREE = [
  '1 site to try for 7 days; confirm your email to keep it',
  '25 MB per site',
  '500 pages and 500 short links once you confirm an email',
  'Unlisted pages; take one down or delete it any time',
];
const PRO = [
  '2,500 pages and 2,500 short links',
  '250 MB per site and 10 short names without a random code',
  'How many times each page was opened and each link followed',
  'Password-protected pages',
  'Bigger limits in Todo, Notes and Projects too',
];

function Plan({
  name,
  price,
  items,
  featured = false,
}: {
  name: string;
  price: string;
  items: string[];
  featured?: boolean;
}) {
  return (
    <div className={`rounded-xl border p-4 ${featured ? 'border-band-accent/70 bg-white/5' : 'border-white/20'}`}>
      <p className="font-heading text-lg font-bold text-white">{name}</p>
      <p className="text-[15px] font-semibold text-band-accent">{price}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px]">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function SitesPlans() {
  return (
    <section aria-label="Prices" className="mt-6">
      <div className="grid gap-3 sm:grid-cols-2">
        <Plan name="Free" price="$0" items={FREE} />
        <Plan name="Pro" price="$5 a month or $36 a year" items={PRO} featured />
      </div>
      <p className="mt-2 text-[13px]">
        Start free. Go Pro inside the app whenever you need more. Max accounts get 1 GB per site and 100 short names.
        After a paid plan lapses, short names have 30 days of grace.
      </p>
    </section>
  );
}

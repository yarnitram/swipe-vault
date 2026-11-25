import { useEffect, useState, type FormEvent } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useToast } from './Toast';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  disabled?: boolean;
  badge?: string;
}

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', end: true },
  { to: '/offers', label: 'Offers' },
  { to: '/swipes', label: 'Swipe Library' },
  { to: '/review', label: 'Review Queue' },
  { to: '/drafts', label: 'Drafts' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/settings', label: 'Settings' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [search, setSearch] = useState('');
  const [navOpen, setNavOpen] = useState(false);

  // Keep the global search box in sync when on the swipe library.
  useEffect(() => {
    if (location.pathname === '/swipes') {
      setSearch(new URLSearchParams(location.search).get('q') ?? '');
    }
    setNavOpen(false);
  }, [location.pathname, location.search]);

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    const q = search.trim();
    navigate(q ? `/swipes?q=${encodeURIComponent(q)}` : '/swipes');
  };

  const onLogout = async () => {
    try {
      await logout();
    } catch {
      toast.error('Logout request failed; local session cleared.');
    }
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white px-4">
        <button
          type="button"
          className="btn-ghost btn-xs md:hidden"
          aria-label="Toggle navigation"
          aria-expanded={navOpen}
          onClick={() => setNavOpen((o) => !o)}
        >
          ☰
        </button>
        <NavLink to="/" className="text-base font-bold tracking-tight text-indigo-700">
          SwipeVault
        </NavLink>
        <form role="search" onSubmit={onSearch} className="mx-auto w-full max-w-xl">
          <label htmlFor="global-search" className="sr-only">
            Search swipes
          </label>
          <input
            id="global-search"
            type="search"
            className="input"
            placeholder="Search subjects and bodies…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <div className="flex items-center gap-2 text-sm">
          <span className="hidden text-slate-500 lg:inline" title="Signed in">
            {user?.email}
          </span>
          <NavLink to="/settings" className="btn-ghost btn-xs">
            Settings
          </NavLink>
          <button type="button" className="btn-secondary btn-xs" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>
      <div className="flex">
        <nav
          aria-label="Main"
          className={`${navOpen ? 'block' : 'hidden'} fixed inset-y-14 left-0 z-20 w-52 shrink-0 border-r border-slate-200 bg-white p-3 md:sticky md:top-14 md:block md:h-[calc(100vh-3.5rem)]`}
        >
          <ul className="space-y-0.5">
            {NAV.map((item) => (
              <li key={item.to}>
                {item.disabled ? (
                  <span
                    className="flex cursor-not-allowed items-center justify-between rounded-md px-3 py-2 text-sm text-slate-400"
                    aria-disabled="true"
                    title="Available in a later phase"
                  >
                    {item.label}
                    {item.badge && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500">
                        {item.badge}
                      </span>
                    )}
                  </span>
                ) : (
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `block rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                        isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-700 hover:bg-slate-100'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                )}
              </li>
            ))}
          </ul>
        </nav>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

import { NavLink, useNavigate } from 'react-router';

import { useLogout } from '../../api/hooks';
import { CompanyBadge } from './CompanyBadge';
import { RoleSwitcher } from './RoleSwitcher';
import styles from './TopBar.module.css';

const LINKS = [
  { to: '/feed', label: 'Лента' },
  { to: '/analyze', label: 'Проверить новость' },
  { to: '/profile', label: 'Что мы знаем о вас' },
  { to: '/quality', label: 'Качество' },
];

export function Logo() {
  return (
    <span className={styles.logo} aria-label="Альфа Инсайт">
      <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
        <rect width="24" height="24" rx="6" fill="var(--ai-accent)" />
        <path
          d="M12.9 5h-1.8L7.4 16h1.9l.8-2.5h3.8l.8 2.5h1.9L12.9 5zm-2.3 6.9L12 7.7l1.4 4.2h-2.8zM7 17.6h10V19H7z"
          fill="#fff"
        />
      </svg>
      <span>Альфа Инсайт</span>
    </span>
  );
}

export function TopBar() {
  const logout = useLogout();
  const navigate = useNavigate();
  return (
    <header className={styles.bar}>
      <div className={styles.inner}>
        <NavLink to="/" className={styles.home}>
          <Logo />
        </NavLink>
        <div className={styles.company}>
          <CompanyBadge />
        </div>
        <nav className={styles.nav} aria-label="Разделы">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) => (isActive ? `${styles.link} ${styles.active}` : styles.link)}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.right}>
          <RoleSwitcher compact />
          <button
            type="button"
            className={styles.exit}
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login') })}
          >
            Выйти
          </button>
        </div>
      </div>
    </header>
  );
}

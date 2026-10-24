import { Link } from 'react-router';

export default function NotFoundPage() {
  return (
    <div className="page" style={{ textAlign: 'center', paddingTop: 96 }}>
      <h1 className="h1">Страница не найдена</h1>
      <p className="secondary">
        <Link to="/">На главную</Link>
      </p>
    </div>
  );
}

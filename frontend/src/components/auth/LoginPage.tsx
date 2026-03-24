import React, { useState } from 'react';
import { useAuthStore } from '@/store/auth';
import './LoginPage.css';

export const LoginPage: React.FC = () => {
  const { login, error } = useAuthStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await login(username, password);
    setSubmitting(false);
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <h1 className="login-title">AgentHub</h1>
        <p className="login-subtitle">Sign in with your system account</p>
        <form onSubmit={handleSubmit} className="login-form">
          <input
            className="login-input"
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
          />
          <input
            className="login-input"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          {error && <div className="login-error">{error}</div>}
          <button
            className="login-button"
            type="submit"
            disabled={submitting || !username || !password}
          >
            {submitting ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
};

import { Link } from "react-router-dom";

import { useProfile } from "./ProfileContext";


export default function AppHeader() {
  const { profile, clearProfile } = useProfile();

  return (
    <header className="app-header">
      <Link className="app-brand" to="/">
        <span className="app-brand-mark">M</span>
        <span>Media App</span>
      </Link>

      <nav className="app-nav" aria-label="Main navigation">
        <Link to="/">Browse</Link>
        <Link to="/admin">Admin</Link>
        {profile ? (
          <button
            className="profile-chip"
            type="button"
            onClick={clearProfile}
            aria-label={`Switch profile. Current profile: ${profile.name}`}
          >
            <span>{profile.name.slice(0, 1).toUpperCase()}</span>
            {profile.name}
          </button>
        ) : null}
      </nav>
    </header>
  );
}

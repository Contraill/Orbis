import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  createProfile as createProfileRequest,
  listProfiles,
  getSetup, ownerSession, logoutOwner,
} from "../api";
import type { Profile, ProfileInput, SetupStatus } from "../types";


const STORAGE_KEY = "media-app.selected-profile.v1";


interface ProfileContextValue {
  profiles: Profile[];
  profile: Profile | null;
  loading: boolean;
  error: string | null;
  selectProfile: (profileId: number) => void;
  clearProfile: () => void;
  createProfile: (profile: ProfileInput) => Promise<Profile>;
  reload: () => Promise<void>;
  setup: SetupStatus | null;
  admin: boolean;
  authenticate: (token: string) => Promise<void>;
}


const ProfileContext = createContext<ProfileContextValue | null>(null);


function storedProfileId() {
  const value = window.localStorage.getItem(STORAGE_KEY);
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}


export function ProfileProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [adminId, setAdminId] = useState<number | null>(null);
  const [selectedId, setSelectedId] =
    useState<number | null>(storedProfileId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextProfiles, nextSetup] = await Promise.all([listProfiles(), getSetup()]);
      setProfiles(nextProfiles);
      setSetup(nextSetup);
      if (sessionStorage.getItem("orbis.owner-session")) {
        try { setAdminId((await ownerSession()).owner_id); }
        catch { sessionStorage.removeItem("orbis.owner-session"); setAdminId(null); }
      }
      setSelectedId((current) => {
        if (
          current !== null &&
          nextProfiles.some((item) => item.id === current)
        ) {
          return current;
        }
        window.localStorage.removeItem(STORAGE_KEY);
        return null;
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Profiles could not be loaded",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const selectProfile = useCallback((profileId: number) => {
    if (adminId !== null && adminId !== profileId) {
      void logoutOwner().catch(() => {});
      sessionStorage.removeItem("orbis.owner-session");
      setAdminId(null);
    }
    setSelectedId(profileId);
    window.localStorage.setItem(
      STORAGE_KEY,
      String(profileId),
    );
  }, [adminId]);

  const clearProfile = useCallback(() => {
    if (sessionStorage.getItem("orbis.owner-session")) void logoutOwner().catch(() => {});
    sessionStorage.removeItem("orbis.owner-session");
    setAdminId(null);
    setSelectedId(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  const authenticate = useCallback(async (token: string) => {
    sessionStorage.setItem("orbis.owner-session", token);
    const session = await ownerSession();
    setAdminId(session.owner_id);
    setSelectedId(session.owner_id);
    localStorage.setItem(STORAGE_KEY, String(session.owner_id));
    await reload();
  }, [reload]);

  const createProfile = useCallback(async (values: ProfileInput) => {
    const created = await createProfileRequest(values);
    setProfiles((current) => [...current, created]);
    selectProfile(created.id);
    return created;
  }, [selectProfile]);

  const profile = profiles.find(
    (item) => item.id === selectedId,
  ) ?? null;
  const admin = Boolean(profile?.is_owner && adminId === profile.id);
  useEffect(() => { document.documentElement.lang = profile?.locale ?? setup?.locale ?? "en-US"; }, [profile?.locale, setup?.locale]);

  const value = useMemo<ProfileContextValue>(() => ({
    profiles,
    profile,
    loading,
    error,
    selectProfile,
    clearProfile,
    createProfile,
    reload,
    setup, admin, authenticate,
  }), [
    profiles,
    profile,
    loading,
    error,
    selectProfile,
    clearProfile,
    createProfile,
    reload,
    setup, admin, authenticate,
  ]);

  return (
    <ProfileContext.Provider value={value}>
      {children}
    </ProfileContext.Provider>
  );
}


export function useProfile() {
  const value = useContext(ProfileContext);
  if (!value) {
    throw new Error("useProfile must be used inside ProfileProvider");
  }
  return value;
}

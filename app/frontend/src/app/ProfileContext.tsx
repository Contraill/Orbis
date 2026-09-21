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
} from "../api";
import type { Profile } from "../types";


const STORAGE_KEY = "media-app.selected-profile.v1";


interface ProfileContextValue {
  profiles: Profile[];
  profile: Profile | null;
  loading: boolean;
  error: string | null;
  selectProfile: (profileId: number) => void;
  clearProfile: () => void;
  createProfile: (name: string) => Promise<Profile>;
  reload: () => Promise<void>;
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
  const [selectedId, setSelectedId] =
    useState<number | null>(storedProfileId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextProfiles = await listProfiles();
      setProfiles(nextProfiles);
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
    setSelectedId(profileId);
    window.localStorage.setItem(
      STORAGE_KEY,
      String(profileId),
    );
  }, []);

  const clearProfile = useCallback(() => {
    setSelectedId(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  const createProfile = useCallback(async (name: string) => {
    const created = await createProfileRequest(name);
    setProfiles((current) => [...current, created]);
    selectProfile(created.id);
    return created;
  }, [selectProfile]);

  const profile = profiles.find(
    (item) => item.id === selectedId,
  ) ?? null;

  const value = useMemo<ProfileContextValue>(() => ({
    profiles,
    profile,
    loading,
    error,
    selectProfile,
    clearProfile,
    createProfile,
    reload,
  }), [
    profiles,
    profile,
    loading,
    error,
    selectProfile,
    clearProfile,
    createProfile,
    reload,
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

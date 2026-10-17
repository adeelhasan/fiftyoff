import { BigShoulders_900Black } from '@expo-google-fonts/big-shoulders';
import { IBMPlexMono_600SemiBold } from '@expo-google-fonts/ibm-plex-mono';
import { IBMPlexSans_400Regular, IBMPlexSans_600SemiBold, IBMPlexSans_700Bold } from '@expo-google-fonts/ibm-plex-sans';
import { PermanentMarker_400Regular } from '@expo-google-fonts/permanent-marker';
import { useFonts } from 'expo-font';
import { DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';

import { api } from '@/lib/api';
import { PrefsProvider, usePrefs } from '@/lib/prefs';
import { SessionProvider } from '@/lib/session';
import { C } from '@/lib/tokens';

SplashScreen.preventAutoHideAsync();

const theme = {
  ...DefaultTheme,
  colors: { ...DefaultTheme.colors, background: C.ground, primary: C.stamp, text: C.ink, card: C.slip, border: C.ruleSoft },
};

export default function RootLayout() {
  const [fonts] = useFonts({
    BigShoulders_900Black,
    IBMPlexSans_400Regular,
    IBMPlexSans_600SemiBold,
    IBMPlexSans_700Bold,
    IBMPlexMono_600SemiBold,
    PermanentMarker_400Regular,
  });
  return (
    <ThemeProvider value={theme}>
      <PrefsProvider>
        <SessionProvider>
          <StatusBar style="dark" />
          <Root fonts={fonts} />
        </SessionProvider>
      </PrefsProvider>
    </ThemeProvider>
  );
}

function Root({ fonts }: { fonts: boolean }) {
  const { prefs, ready, set } = usePrefs();

  useEffect(() => {
    if (fonts && ready) SplashScreen.hideAsync();
  }, [fonts, ready]);

  // A weekly-email address kept on the phone (the endpoint wasn't there yet) is sent once it is.
  useEffect(() => {
    const w = prefs.weekly;
    if (!ready || w?.state !== 'saved') return;
    api.weekly(w.email).then((state) => state === 'sent' && set({ weekly: { ...w, state } }), () => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  if (!fonts || !ready) return null;
  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: C.ground } }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="deal/[slug]" />
      <Stack.Screen name="shelf/[id]" />
      <Stack.Screen name="search" options={{ animation: 'fade' }} />
      <Stack.Screen name="sizes" />
      <Stack.Screen name="onboarding" options={{ presentation: 'fullScreenModal', gestureEnabled: false }} />
      <Stack.Screen name="alert-sheet" options={{ presentation: 'modal' }} />
      <Stack.Screen name="sign-in" options={{ presentation: 'modal' }} />
    </Stack>
  );
}

import { Stack } from 'expo-router';

import { C } from '@/lib/tokens';

export default function OnboardingLayout() {
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: C.ground } }} />;
}

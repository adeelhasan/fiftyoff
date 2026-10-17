import { Redirect } from 'expo-router';
import { NativeTabs } from 'expo-router/unstable-native-tabs';

import { usePrefs } from '@/lib/prefs';
import { C, F } from '@/lib/tokens';

export default function TabsLayout() {
  const { prefs } = usePrefs();
  if (!prefs.onboarded) return <Redirect href="/onboarding" />;
  return (
    <NativeTabs tintColor={C.stamp} labelStyle={{ fontFamily: F.textSemi }}>
      <NativeTabs.Trigger name="index">
        <NativeTabs.Trigger.Label>Today</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'square.text.square', selected: 'square.text.square.fill' }} md="home" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="deals">
        <NativeTabs.Trigger.Label>All deals</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'square.grid.2x2', selected: 'square.grid.2x2.fill' }} md="grid_view" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="alerts">
        <NativeTabs.Trigger.Label>Alerts</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'bell', selected: 'bell.fill' }} md="notifications" />
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name="settings">
        <NativeTabs.Trigger.Label>Settings</NativeTabs.Trigger.Label>
        <NativeTabs.Trigger.Icon sf={{ default: 'gearshape', selected: 'gearshape.fill' }} md="settings" />
      </NativeTabs.Trigger>
    </NativeTabs>
  );
}

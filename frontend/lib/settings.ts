import { supabase } from './supabase';
import { Settings } from '@/types';

export async function getSettings(): Promise<Settings | null> {
  try {
    const { data, error } = await supabase
      .from('settings')
      .select('*')
      .eq('id', 'main')
      .single();

    if (error) {
      console.warn('Could not fetch settings:', error.message);
      return null;
    }

    return data as Settings;
  } catch (err) {
    console.error('Error in getSettings:', err);
    return null;
  }
}

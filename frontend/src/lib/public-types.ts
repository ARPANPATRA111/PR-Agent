export interface VersionedRecord {
  id: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface WorkLog extends VersionedRecord {
  original_text: string;
  cleaned_text: string | null;
  category: string | null;
  tags: string[];
  logged_at_utc: string;
  user_local_date: string;
  timezone: string;
  capture_source: string;
}

export interface Note extends VersionedRecord {
  title: string;
  body: string;
  tags: string[];
  pinned: boolean;
  capture_source: string;
}

export interface Reminder extends VersionedRecord {
  title: string;
  description: string | null;
  timezone: string;
  schedule_type: 'once' | 'daily' | 'weekly';
  scheduled_local_time: string | null;
  next_run_at_utc: string | null;
  recurrence_rule: Record<string, unknown> | null;
  enabled: boolean;
}

export interface LedgerEntry extends VersionedRecord {
  direction: 'expense' | 'income';
  amount_minor: number;
  currency: string;
  category: string | null;
  description: string;
  transaction_at_utc: string;
  user_local_date: string;
  timezone: string;
  capture_source: string;
}

export interface LedgerSummary {
  currency: string;
  expense_minor: number;
  income_minor: number;
}

export interface Goal extends VersionedRecord {
  title: string;
  description: string | null;
  target_value: string | null;
  current_value: string;
  unit: string | null;
  start_date: string;
  due_date: string | null;
  status: 'active' | 'paused' | 'completed';
}

export interface NutritionItem extends VersionedRecord {
  nutrition_log_id: number;
  original_item_text: string;
  normalized_name: string;
  quantity_value: string | null;
  quantity_unit: string | null;
  portion_description: string | null;
  estimated_grams: string | null;
  calories: string;
  protein_grams: string;
  carbohydrate_grams: string | null;
  fat_grams: string | null;
  estimation_source: string;
  confidence: string | null;
  visible_assumptions: string[];
  user_modified: boolean;
}

export interface NutritionLog extends VersionedRecord {
  meal_name: string | null;
  logged_at_utc: string;
  user_local_date: string;
  timezone: string;
  original_text: string;
  status: 'draft' | 'confirmed' | 'unestimated';
  total_calories: string;
  total_protein_grams: string;
  total_carbohydrate_grams: string | null;
  total_fat_grams: string | null;
  estimation_source: string;
  overall_confidence: string | null;
  visible_assumptions: string[];
  provider_metadata: Record<string, unknown>;
  clarification_question: string | null;
  confirmed_by_user: boolean;
  user_modified: boolean;
  items: NutritionItem[];
}

export interface NutritionSummary {
  start_date: string;
  end_date: string;
  confirmed_meals: number;
  unestimated_meals: number;
  total_calories: string;
  total_protein_grams: string;
  total_carbohydrate_grams: string | null;
  total_fat_grams: string | null;
  average_daily_calories: string;
  average_daily_protein_grams: string;
  calorie_target: string | null;
  protein_target_grams: string | null;
}

export interface NutritionPreferences {
  owner_id: number;
  version: number;
  timezone: string;
  calorie_target: string | null;
  protein_target_grams: string | null;
  carbohydrate_target_grams: string | null;
  fat_target_grams: string | null;
  default_milk_serving_ml: string;
  measurement_system: 'metric' | 'imperial';
  nutrition_confirmation_required: boolean;
  created_at: string;
  updated_at: string;
}

export interface AppSettings {
  timezone: string;
  display_name: string;
  default_tone: string;
  nudge_enabled: boolean;
  nudge_time: string;
  daily_reflection_time: string;
  weekly_summary_day: string;
  weekly_summary_time: string;
}

export type ScreenName =
  | 'home'
  | 'work'
  | 'notes'
  | 'reminders'
  | 'money'
  | 'nutrition'
  | 'goals'
  | 'settings'
  | 'export'
  | 'account';

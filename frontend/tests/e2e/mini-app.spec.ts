import { expect, type Page, test } from '@playwright/test';

interface MockState {
  work: Array<Record<string, unknown>>;
  notes: Array<Record<string, unknown>>;
  reminders: Array<Record<string, unknown>>;
  ledger: Array<Record<string, unknown>>;
  goals: Array<Record<string, unknown>>;
  nutrition: Array<Record<string, unknown>>;
  expireNotes?: boolean;
}

function timestamps() {
  const value = new Date().toISOString();
  return { created_at: value, updated_at: value };
}

async function installTelegram(page: Page) {
  await page.route(
    'https://telegram.org/js/telegram-web-app.js',
    (route) => route.abort(),
  );
  await page.addInitScript(() => {
    window.Telegram = {
      WebApp: {
        initData: 'signed-telegram-init-data',
        colorScheme: 'light',
        ready: () => undefined,
        expand: () => undefined,
      },
    };
  });
}

async function mockApi(
  page: Page,
  validAuth = true,
  nutritionProviderDisabled = false,
) {
  const state: MockState = {
    work: [],
    notes: [],
    reminders: [],
    ledger: [],
    goals: [],
    nutrition: [],
  };

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const rawBody = request.postData();
    const payload = rawBody
      ? (JSON.parse(rawBody) as Record<string, unknown>)
      : null;

    const json = async (value: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(value),
        headers: {
          'Access-Control-Allow-Origin': 'http://127.0.0.1:3000',
          'Access-Control-Allow-Credentials': 'true',
        },
      });

    if (method === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': 'http://127.0.0.1:3000',
          'Access-Control-Allow-Credentials': 'true',
          'Access-Control-Allow-Headers':
            'Content-Type, X-CSRF-Token, Authorization',
          'Access-Control-Allow-Methods':
            'GET, POST, PUT, PATCH, DELETE, OPTIONS',
        },
      });
      return;
    }

    if (path === '/api/auth/telegram') {
      if (!validAuth) {
        await json({ detail: 'Invalid Telegram signature' }, 401);
        return;
      }
      await json({
        success: true,
        access_token: 'session-token',
        csrf_token: 'csrf-token',
        expires_in: 900,
        user: {
          id: 1,
          telegram_id: 101,
          first_name: 'Alice',
        },
      });
      return;
    }
    if (path === '/api/auth/logout') {
      await json({ success: true });
      return;
    }
    if (path === '/api/v2/schedule-preferences') {
      await json({
        preference_version: 1,
        digest_version: 1,
        timezone: 'UTC',
        sunday_digest_enabled: false,
        sunday_digest_time: '20:00:00',
        next_digest_at_utc: null,
      });
      return;
    }
    if (path === '/api/v2/nutrition/preferences') {
      await json({
        owner_id: 1,
        version: 1,
        timezone: 'UTC',
        calorie_target: '2000.00',
        protein_target_grams: '100.000',
        carbohydrate_target_grams: null,
        fat_target_grams: null,
        default_milk_serving_ml: '250.00',
        measurement_system: 'metric',
        nutrition_confirmation_required: true,
        ...timestamps(),
      });
      return;
    }
    if (path === '/api/v2/account/export') {
      await json({ message: 'Export requested.' });
      return;
    }
    if (path === '/api/v2/account' && method === 'DELETE') {
      await route.fulfill({ status: 204 });
      return;
    }

    if (path === '/api/v2/work-logs') {
      if (method === 'POST') {
        const record = {
          id: 1,
          version: 1,
          original_text: payload?.original_text,
          cleaned_text: null,
          category: payload?.category || null,
          tags: [],
          logged_at_utc: new Date().toISOString(),
          user_local_date: '2026-07-31',
          timezone: 'UTC',
          capture_source: 'mini_app',
          ...timestamps(),
        };
        state.work = [record];
        await json(record, 201);
      } else {
        await json(state.work);
      }
      return;
    }
    if (path.startsWith('/api/v2/work-logs/') && method === 'PATCH') {
      state.work[0] = {
        ...state.work[0],
        original_text: payload?.original_text,
        version: 2,
      };
      await json(state.work[0]);
      return;
    }

    if (path === '/api/v2/notes') {
      if (state.expireNotes) {
        await json({ detail: 'Authentication required' }, 401);
      } else if (method === 'POST') {
        const record = {
          id: 1,
          version: 1,
          title: String(payload?.body).slice(0, 80),
          body: payload?.body,
          tags: [],
          pinned: false,
          capture_source: 'mini_app',
          ...timestamps(),
        };
        state.notes = [record];
        await json(record, 201);
      } else {
        await json(state.notes);
      }
      return;
    }
    if (path === '/api/v2/notes/999') {
      await json({ detail: 'Record not found.' }, 404);
      return;
    }
    if (path.startsWith('/api/v2/notes/') && method === 'DELETE') {
      state.notes = [];
      await route.fulfill({ status: 204 });
      return;
    }

    if (path === '/api/v2/reminders') {
      if (method === 'POST') {
        const record = {
          id: 1,
          version: 1,
          title: payload?.title,
          description: null,
          timezone: payload?.timezone,
          schedule_type: payload?.schedule_type,
          scheduled_local_time: '19:00:00',
          next_run_at_utc: new Date(Date.now() + 86_400_000).toISOString(),
          recurrence_rule: null,
          enabled: true,
          ...timestamps(),
        };
        state.reminders = [record];
        await json(record, 201);
      } else {
        await json(state.reminders);
      }
      return;
    }

    if (path === '/api/v2/ledger/summary') {
      const expense = state.ledger.reduce(
        (total, item) => total + Number(item.amount_minor || 0),
        0,
      );
      await json(
        expense
          ? [{ currency: 'INR', expense_minor: expense, income_minor: 0 }]
          : [],
      );
      return;
    }
    if (path === '/api/v2/ledger') {
      if (method === 'POST') {
        const record = {
          id: 1,
          version: 1,
          direction: payload?.direction,
          amount_minor: Math.round(Number(payload?.amount) * 100),
          currency: payload?.currency,
          category: null,
          description: payload?.description,
          transaction_at_utc: new Date().toISOString(),
          user_local_date: '2026-07-31',
          timezone: 'UTC',
          capture_source: 'mini_app',
          ...timestamps(),
        };
        state.ledger = [record];
        await json(record, 201);
      } else {
        await json(state.ledger);
      }
      return;
    }

    if (path === '/api/v2/goals') {
      await json(state.goals);
      return;
    }

    if (path === '/api/v2/nutrition/summary') {
      const confirmed = state.nutrition.filter(
        (item) => item.status === 'confirmed',
      );
      const protein = confirmed.reduce(
        (total, item) => total + Number(item.total_protein_grams || 0),
        0,
      );
      const calories = confirmed.reduce(
        (total, item) => total + Number(item.total_calories || 0),
        0,
      );
      await json({
        start_date: '2026-07-31',
        end_date: '2026-07-31',
        confirmed_meals: confirmed.length,
        unestimated_meals: 0,
        total_calories: calories.toFixed(2),
        total_protein_grams: protein.toFixed(3),
        total_carbohydrate_grams: '0.000',
        total_fat_grams: '0.000',
        average_daily_calories: calories.toFixed(2),
        average_daily_protein_grams: protein.toFixed(3),
        calorie_target: '2000.00',
        protein_target_grams: '100.000',
      });
      return;
    }
    if (path === '/api/v2/nutrition') {
      if (method === 'POST') {
        const record = {
          id: 1,
          version: 2,
          meal_name: payload?.meal_name,
          logged_at_utc: new Date().toISOString(),
          user_local_date: '2026-07-31',
          timezone: 'UTC',
          original_text: payload?.original_text,
          status: 'draft',
          total_calories: nutritionProviderDisabled ? '0.00' : '132.50',
          total_protein_grams: nutritionProviderDisabled ? '0.000' : '9.150',
          total_carbohydrate_grams: nutritionProviderDisabled ? '0.000' : '0.600',
          total_fat_grams: nutritionProviderDisabled ? '0.000' : '10.400',
          estimation_source: nutritionProviderDisabled
            ? 'provider_unavailable'
            : 'bundled_reference:2026.07',
          overall_confidence: nutritionProviderDisabled ? null : '0.8000',
          visible_assumptions: [],
          provider_metadata: {},
          clarification_question: nutritionProviderDisabled
            ? 'Estimation is unavailable. Save as an unestimated food note or enter calories and protein manually.'
            : null,
          confirmed_by_user: false,
          user_modified: false,
          items: nutritionProviderDisabled ? [] : [
            {
              id: 1,
              nutrition_log_id: 1,
              version: 1,
              original_item_text: '50 g paneer',
              normalized_name: 'paneer',
              quantity_value: '50.000',
              quantity_unit: 'g',
              portion_description: '50 g',
              estimated_grams: '50.000',
              calories: '132.50',
              protein_grams: '9.150',
              carbohydrate_grams: '0.600',
              fat_grams: '10.400',
              estimation_source: 'bundled_reference:2026.07',
              confidence: '0.8000',
              visible_assumptions: [],
              user_modified: false,
              ...timestamps(),
            },
          ],
          ...timestamps(),
        };
        state.nutrition = [record];
        await json(record, 201);
      } else {
        await json(state.nutrition);
      }
      return;
    }
    if (path === '/api/v2/nutrition/1/manual') {
      const manualItems =
        (payload?.items as Array<Record<string, unknown>> | undefined) || [];
      const manualValues = manualItems[0] || {};
      const manualItem = {
        id: 1,
        nutrition_log_id: 1,
        version: 1,
        ...manualValues,
        estimation_source: 'manual:user',
        user_modified: true,
        ...timestamps(),
      };
      state.nutrition[0] = {
        ...state.nutrition[0],
        version: 3,
        status: 'confirmed',
        total_calories: manualValues.calories,
        total_protein_grams: manualValues.protein_grams,
        estimation_source: 'manual',
        clarification_question: null,
        confirmed_by_user: true,
        user_modified: true,
        items: [manualItem],
      };
      await json(state.nutrition[0]);
      return;
    }
    if (path === '/api/v2/nutrition/1/confirm') {
      state.nutrition[0] = {
        ...state.nutrition[0],
        status: 'confirmed',
        version: 3,
      };
      await json(state.nutrition[0]);
      return;
    }
    if (path === '/api/v2/nutrition/1/items/1') {
      const item = {
        ...(state.nutrition[0].items as Array<Record<string, unknown>>)[0],
        quantity_value: payload?.quantity_value,
        quantity_unit: payload?.quantity_unit,
        calories: payload?.calories,
        protein_grams: payload?.protein_grams,
        version: 2,
        user_modified: true,
      };
      state.nutrition[0] = {
        ...state.nutrition[0],
        items: [item],
        total_calories: payload?.calories,
        total_protein_grams: payload?.protein_grams,
        user_modified: true,
        version: 4,
      };
      await json(state.nutrition[0]);
      return;
    }

    await json({ detail: `Unhandled mock route ${method} ${path}` }, 500);
  });
  return state;
}

test.beforeEach(async ({ page }) => {
  await installTelegram(page);
});

test('valid Mini App authentication has no ID or password prompt', async ({
  page,
}) => {
  await mockApi(page);
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Today', exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Telegram ID')).toHaveCount(0);
  await expect(page.getByLabel('Dashboard password')).toHaveCount(0);
});

test('invalid Telegram authentication is rejected', async ({ page }) => {
  await mockApi(page, false);
  await page.goto('/');
  await expect(page.getByText('Invalid Telegram signature')).toBeVisible();
});

test('mobile CRUD flows, nutrition totals, and cross-user denial', async ({
  page,
}) => {
  await mockApi(page);
  await page.goto('/');

  await page.getByRole('button', { name: 'Open Work' }).click();
  await page.getByRole('button', { name: 'Add' }).click();
  await page.getByLabel('What did you complete?').fill('Created public API');
  await page.getByRole('button', { name: 'Add work log' }).click();
  await expect(page.getByText('Created public API')).toBeVisible();
  await page.getByRole('button', { name: 'Edit' }).click();
  await page.getByLabel('What did you complete?').fill('Edited public API');
  await page.getByRole('button', { name: 'Save edit' }).click();
  await expect(page.getByText('Edited public API')).toBeVisible();

  await page.getByRole('button', { name: 'Open Notes' }).click();
  await page.getByRole('button', { name: 'Add' }).click();
  await page.getByRole('textbox', { name: 'Note', exact: true }).fill('Private note');
  await page.getByRole('button', { name: 'Add note' }).click();
  await expect(page.getByText('Private note').first()).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText('No notes yet.')).toBeVisible();

  await page.getByRole('button', { name: 'Open Reminders' }).click();
  await page.getByRole('button', { name: 'Add' }).click();
  await page
    .getByRole('textbox', { name: 'Reminder', exact: true })
    .fill('Submit assignment');
  await page.getByLabel('First occurrence').fill('2030-08-10T19:00');
  await page.getByRole('button', { name: 'Add reminder' }).click();
  await expect(page.getByText('Submit assignment')).toBeVisible();

  await page.getByRole('button', { name: 'Open Money' }).click();
  await page.getByRole('button', { name: 'Add' }).click();
  await page.getByLabel('Amount').fill('240');
  await page.getByLabel('Description').fill('Dinner');
  await page.getByRole('button', { name: 'Add transaction' }).click();
  await expect(page.getByText('Dinner')).toBeVisible();

  await page.getByRole('button', { name: 'Open Nutrition' }).click();
  await page.getByRole('button', { name: 'Add' }).click();
  await page.getByLabel('Food description').fill('50 g paneer');
  await page.getByRole('button', { name: 'Estimate meal' }).click();
  await page.getByRole('button', { name: 'Confirm meal' }).click();
  await expect(page.getByText(/9\.150 g/).first()).toBeVisible();
  await page.getByRole('button', { name: 'Edit paneer serving' }).click();
  await page.getByLabel('Quantity').fill('100');
  await page.getByLabel('Calories').fill('265');
  await page.getByLabel('Protein grams').fill('18.3');
  await page.getByRole('button', { name: 'Save serving' }).click();
  await expect(page.getByText(/18\.3 g protein/).first()).toBeVisible();

  const denied = await page.evaluate(async () => {
    const response = await fetch(
      'http://localhost:8000/api/v2/notes/999?telegram_id=202',
      { credentials: 'include' },
    );
    return response.status;
  });
  expect(denied).toBe(404);
});

test('session expiry resets authentication and Mini App has no logout control', async ({ page }) => {
  const state = await mockApi(page);
  await page.goto('/');
  state.expireNotes = true;
  await page.getByRole('button', { name: 'Open Notes' }).click();
  await expect(
    page.getByText('Your session expired. Reopen or retry the Mini App.'),
  ).toBeVisible();

  await page.reload();
  state.expireNotes = false;
  await expect(
    page.getByRole('heading', { name: 'Today', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Log out and clear this session' }),
  ).toHaveCount(0);
});

test('provider-disabled nutrition accepts explicit manual values', async ({
  page,
}) => {
  await mockApi(page, true, true);
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Nutrition' }).click();
  await page.getByRole('button', { name: 'Add' }).click();
  await page.getByLabel('Food description').fill('Homemade lunch');
  await page.getByRole('button', { name: 'Estimate meal' }).click();
  await expect(page.getByText(/Estimation is unavailable/)).toBeVisible();
  await page
    .getByRole('button', { name: 'Enter calories and protein' })
    .click();
  await page.getByLabel('Food name').fill('Homemade lunch');
  await page.getByLabel('Calories').fill('650');
  await page.getByLabel('Protein grams').fill('31');
  await page.getByRole('button', { name: 'Save manual values' }).click();
  await expect(page.getByText(/650 kcal/).first()).toBeVisible();
  await expect(page.getByText(/31 g protein/).first()).toBeVisible();
});

test('account deletion requires explicit confirmation', async ({ page }) => {
  await mockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Account' }).click();
  const deleteButton = page.getByRole('button', { name: 'Delete my account' });
  await expect(deleteButton).toBeDisabled();
  await page.getByLabel('Confirmation phrase').fill('DELETE MY ACCOUNT');
  await page
    .getByLabel('I understand that confirmed deletion cannot be undone.')
    .check();
  page.once('dialog', (dialog) => dialog.accept());
  await deleteButton.click();
  await expect(
    page.getByText('Your session expired. Reopen or retry the Mini App.'),
  ).toBeVisible();
});

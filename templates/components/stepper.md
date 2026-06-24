# Report Stepper Component

A reusable, responsive stepper component that provides consistent navigation across all report pages in the Petty Cash Management System.

## Overview

The stepper component displays a 6-step progress indicator for the report workflow:
1. **Opening** - Initial balance and cash additions
2. **Sales** - Electronic, delivery, and cash sales
3. **Expenses** - Business expense tracking
4. **Deposit** - Bank deposit amounts
5. **Cash Count** - Physical cash verification
6. **Ending** - Final reconciliation and submission

## Usage

### Basic Implementation

Simply include the component in any report page template:

```html
{% include 'components/stepper.html' %}
```

### Required Template Variables

The component expects these variables to be available in the template context:

- `current_section` (string): The current active section (e.g., "opening", "sales", "expenses", "deposit", "cash_count", "ending")
- `completed_sections` (list): Array of completed sections (e.g., ["opening", "sales"])

### Example Route Implementation

```python
@app.route('/report/opening')
def report_opening():
    return render_template('report/opening.html',
        current_section="opening",  # Always set to current page
        completed_sections=existing_draft.completed_sections or [],
        # ... other template variables
    )
```

## Visual States

### Step Indicators

1. **Current Active Step** (Blue with arrow)
   - Background: `bg-blue-600`
   - Shows blue arrow pointing up
   - Indicates the page user is currently viewing

2. **Completed Steps** (Dark teal)
   - Background: `bg-[#006666]`
   - Clickable and navigable
   - Shows progress through the workflow

3. **Accessible Pending Steps** (Gray, clickable)
   - Background: `bg-gray-300`
   - Only clickable if previous step is completed
   - Allows forward navigation within workflow

4. **Inaccessible Pending Steps** (Gray, not clickable)
   - Background: `bg-gray-300`
   - Cursor: `cursor-not-allowed`
   - Prevents skipping workflow steps

### Progress Lines

- **Completed connections**: Dark teal (`bg-[#006666]`)
- **Pending connections**: Light gray (`bg-gray-300`)
- Lines update based on `completed_sections` array

## Navigation Logic

### Click Behavior

- **Completed steps**: Navigate to that step's page
- **Current step**: No navigation (already on page)
- **Accessible pending**: Navigate to that step's page
- **Inaccessible pending**: No navigation (click disabled)

### Step Access Control

Users can only navigate to steps that are:
1. Already completed, OR
2. The next logical step in the sequence

This prevents workflow skipping and ensures data integrity.

## Responsive Design

- **Mobile**: 6x6 circles with 12px text
- **Desktop**: 8x8 circles with 14px text
- **Hover effects**: Scale transform and color transitions
- **Touch-friendly**: Appropriate spacing for mobile devices

## Dependencies

- **Tailwind CSS**: For styling and responsive classes
- **Jinja2**: For template logic and variable interpolation
- **JavaScript**: `navigateToStep()` function must be available in parent template

## Maintenance

### Adding New Steps

To add a new step to the workflow:

1. Update the progress lines section
2. Add the new step HTML structure
3. Update the navigation logic
4. Ensure backend routes pass correct `current_section`

### Styling Updates

All styling is contained within the component. To modify:
- Colors: Update Tailwind classes
- Sizing: Modify responsive breakpoints
- Animations: Adjust transition classes

## Troubleshooting

### Common Issues

1. **Blue icon not showing**: Ensure `current_section` matches the page name exactly
2. **Steps not clickable**: Check if `completed_sections` includes previous steps
3. **Progress lines not updating**: Verify `completed_sections` is being passed correctly

### Debug Variables

Add these to your template for debugging:

```html
<!-- Debug Info -->
<div class="text-xs text-gray-500">
  Current: {{ current_section }}<br>
  Completed: {{ completed_sections|join(', ') }}
</div>
```

## Version History

- **v1.0**: Initial implementation with 6-step workflow
- **v1.1**: Added responsive design and hover effects
- **v1.2**: Fixed navigation logic and step access control
- **v1.3**: Improved accessibility and touch support

---

*This component is part of the Petty Cash Management System and should not be used outside of this application without proper modification.*

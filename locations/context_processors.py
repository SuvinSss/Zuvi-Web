def delivery_location(request):
    """Expose the shopper's session-selected delivery point to every template."""
    return {"delivery_location": request.session.get("delivery_location")}

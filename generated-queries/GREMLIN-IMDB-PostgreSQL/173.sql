SELECT count(*)
FROM cast_info, comp_cast_type, complete_cast, movie_keyword, movie_link, role_type, title
WHERE comp_cast_type.kind = 'complete+verified'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;

SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((role_type CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN comp_cast_type) CROSS JOIN cast_info) CROSS JOIN movie_keyword
WHERE comp_cast_type.kind = 'complete+verified'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
